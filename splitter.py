"""Split a Canvas course export (.imscc) into one .imscc package per module.

Each module package keeps:
  * the module (its items, text headers and settings) in the manifest and course_settings/module_meta.xml;
  * every page / assignment / quiz / discussion / link in the module, with their dependencies
    (e.g. a quiz's non_cc_assessments file, a discussion's topic file);
  * every file and image those items use ($IMS-CC-FILEBASE$ paths and file_ref links);
  * the course_settings folder, which Canvas needs to import the package.
Nothing from other modules is included. Import with: Settings > Import Course Content >
Canvas Course Export Package > Select specific content.
"""
from __future__ import annotations

import copy
import html
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from urllib.parse import unquote

from lxml import etree

FILEBASE_RE = re.compile(r"\$IMS[-_]CC[-_]FILEBASE\$/([^\"'<>?#\s]+)")
OBJREF_RE = re.compile(r"(?:file_ref|\$CANVAS_OBJECT_REFERENCE\$/\w+)/([A-Za-z0-9_\-]+)")
WIKI_RE = re.compile(r"\$WIKI_REFERENCE\$/pages/([^\"'<>?#\s]+)")
TEXT_EXT = (".html", ".htm", ".xml", ".qti", ".txt", ".json")
MODULE_NUM_RE = re.compile(r"\bmodule\s*0*(\d+)\b", re.I)


def local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def kids(el, name):
    return [c for c in el if local(c.tag) == name]


def title_of(item) -> str:
    t = kids(item, "title")
    return (t[0].text or "").strip() if t else ""


@dataclass
class Module:
    index: int
    ident: str
    title: str
    number: int | None
    element: object = field(repr=False)

    @property
    def label(self) -> str:
        return f"Module {self.number}" if self.number is not None else self.title or f"Module item {self.index}"

    @property
    def file_stem(self) -> str:
        if self.number is not None:
            return f"Module_{self.number:02d}"
        return "Module_" + (re.sub(r"[^A-Za-z0-9]+", "_", self.title).strip("_")[:40] or str(self.index))

    def refs(self) -> list[str]:
        return [i.get("identifierref") for i in self.element.iter() if local(i.tag) == "item" and i.get("identifierref")]

    def items(self) -> list[tuple[str, str | None]]:
        return [(title_of(i), i.get("identifierref")) for i in self.element.iter()
                if local(i.tag) == "item" and i is not self.element]


class Course:
    def __init__(self, path_or_bytes):
        data = path_or_bytes if isinstance(path_or_bytes, (bytes, bytearray)) else open(path_or_bytes, "rb").read()
        self.zf = zipfile.ZipFile(io.BytesIO(data))
        self.names = set(self.zf.namelist())
        if "imsmanifest.xml" not in self.names:
            raise ValueError("This is not a Canvas course export: imsmanifest.xml is missing.")
        self.tree = etree.fromstring(self.zf.read("imsmanifest.xml"), etree.XMLParser(remove_blank_text=False))
        self.resources = {r.get("identifier"): r for r in self.tree.iter() if local(r.tag) == "resource"}
        self.by_href = {}
        for rid, r in self.resources.items():
            for h in self.res_files(r):
                self.by_href.setdefault(unquote(h), rid)
        self.modules = self._modules()
        self.settings_res = [rid for rid, r in self.resources.items()
                             if any(h.startswith("course_settings/") for h in self.res_files(r))]

    # ---- structure
    def res_files(self, r) -> list[str]:
        out = [f.get("href") for f in kids(r, "file") if f.get("href")]
        if r.get("href") and r.get("href") not in out:
            out.insert(0, r.get("href"))
        return out

    def res_deps(self, r) -> list[str]:
        return [d.get("identifierref") for d in kids(r, "dependency") if d.get("identifierref")]

    def _organization(self):
        orgs = [e for e in self.tree.iter() if local(e.tag) == "organization"]
        return orgs[0] if orgs else None

    def _module_parent(self):
        org = self._organization()
        if org is None:
            return None
        roots = kids(org, "item")
        # Canvas: organization > item(LearningModules) > item(module) > item(content)
        if len(roots) == 1 and not roots[0].get("identifierref") and kids(roots[0], "item"):
            return roots[0]
        return org

    def _modules(self) -> list[Module]:
        parent = self._module_parent()
        if parent is None:
            return []
        mods = []
        for i, it in enumerate(kids(parent, "item"), 1):
            t = title_of(it)
            m = MODULE_NUM_RE.search(t)
            mods.append(Module(i, it.get("identifier", ""), t, int(m.group(1)) if m else None, it))
        # duplicate numbers (e.g. "Module 3" and "Module 3 Answer Keys") -> keep both, disambiguate file names
        return mods

    # ---- references inside content
    def text(self, name) -> str:
        raw = self.zf.read(name)
        for enc in ("utf-8", "cp1252"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                pass
        return raw.decode("utf-8", "replace")

    def scan(self, name):
        """Files, object ids and wiki pages referenced from one content file."""
        t = html.unescape(self.text(name))
        files = {"web_resources/" + unquote(m) for m in FILEBASE_RE.findall(t)}
        objs = set(OBJREF_RE.findall(t))
        wiki = {unquote(m) for m in WIKI_RE.findall(t)}
        return files, objs, wiki

    # ---- build one package
    def collect(self, mods: list[Module]):
        keep: set[str] = set()
        warnings: list[str] = []
        outside_links: set[str] = set()
        queue = [r for m in mods for r in m.refs()]
        while queue:
            rid = queue.pop()
            if rid in keep:
                continue
            r = self.resources.get(rid)
            if r is None:
                warnings.append(f"Module item points to resource '{rid}', which is not in the package.")
                continue
            keep.add(rid)
            queue += self.res_deps(r)
            for f in self.res_files(r):
                if f not in self.names:
                    warnings.append(f"File listed in the manifest is missing from the export: {f}")
                    continue
                if not f.lower().endswith(TEXT_EXT) or f.startswith("web_resources/"):
                    continue
                files, objs, wiki = self.scan(f)
                for p in files:
                    if p in self.by_href:
                        queue.append(self.by_href[p])
                    else:
                        warnings.append(f"{f} uses '{p}', which is not in the export.")
                for o in objs:
                    if o in self.resources:
                        queue.append(o)
                for slug in wiki:
                    outside_links.add(slug)
        for rid in self.settings_res:
            keep.add(rid)
        # wiki links that point to pages NOT in this package
        kept_hrefs = {unquote(h) for rid in keep for h in self.res_files(self.resources[rid])}
        for slug in sorted(outside_links):
            if f"wiki_content/{slug}.html" not in kept_hrefs:
                warnings.append(f"Link to page '{slug}' – that page is not in this module package "
                                "(the link works once it exists in the course).")
        return keep, sorted(set(warnings))

    def build(self, mods: list[Module]) -> tuple[bytes, dict]:
        keep, warnings = self.collect(mods)
        root = copy.deepcopy(self.tree)
        # organization: keep only the chosen modules
        mod_ids = {m.ident for m in mods}
        parent = None
        for e in root.iter():
            if local(e.tag) == "organization":
                roots = kids(e, "item")
                parent = roots[0] if (len(roots) == 1 and not roots[0].get("identifierref") and kids(roots[0], "item")) else e
                break
        if parent is not None:
            for it in kids(parent, "item"):
                if it.get("identifier") not in mod_ids:
                    parent.remove(it)
        # resources
        for e in root.iter():
            if local(e.tag) == "resources":
                for r in list(e):
                    if local(r.tag) == "resource" and r.get("identifier") not in keep:
                        e.remove(r)
                break
        files = {"imsmanifest.xml"}
        for rid in keep:
            files.update(f for f in self.res_files(self.resources[rid]) if f in self.names)
        files.update(n for n in self.names if n.startswith("course_settings/"))

        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("imsmanifest.xml", etree.tostring(root, xml_declaration=True, encoding="UTF-8"))
            for n in sorted(files - {"imsmanifest.xml"}):
                data = self.zf.read(n)
                if n == "course_settings/module_meta.xml":
                    data = self._filter_module_meta(data, mods)
                src = self.zf.getinfo(n)
                zi = zipfile.ZipInfo(n, date_time=src.date_time)   # fresh entry: never reuse the source ZipInfo
                zi.compress_type = zipfile.ZIP_DEFLATED
                zi.external_attr = src.external_attr
                z.writestr(zi, data)
        info = self.summary(mods, keep, files, warnings)
        info["size"] = len(out.getvalue())
        return out.getvalue(), info

    def _filter_module_meta(self, data: bytes, mods: list[Module]) -> bytes:
        try:
            tree = etree.fromstring(data)
        except etree.XMLSyntaxError:
            return data
        ids = {m.ident for m in mods}
        titles = {m.title for m in mods}
        for mod in [e for e in tree if local(e.tag) == "module"]:
            t = next((c.text for c in mod if local(c.tag) == "title"), "")
            if mod.get("identifier") not in ids and (t or "").strip() not in titles:
                tree.remove(mod)
        # prerequisites pointing to removed modules would block import – drop them
        keep_ids = {e.get("identifier") for e in tree if local(e.tag) == "module"}
        for pr in [e for e in tree.iter() if local(e.tag) == "prerequisite"]:
            ref = next((c.text for c in pr if local(c.tag) == "identifierref"), None)
            if ref and ref not in keep_ids:
                pr.getparent().remove(pr)
        return etree.tostring(tree, xml_declaration=True, encoding="UTF-8")

    def summary(self, mods, keep, files, warnings) -> dict:
        kinds = {"pages": 0, "assignments": 0, "quizzes": 0, "discussions": 0, "links": 0, "files": 0, "headers": 0, "other": 0}
        for m in mods:
            for title, ref in m.items():
                if not ref:
                    kinds["headers"] += 1
                    continue
                r = self.resources.get(ref)
                t = (r.get("type", "") if r is not None else "").lower()
                hrefs = " ".join(self.res_files(r)) if r is not None else ""
                if "wiki_content/" in hrefs:
                    kinds["pages"] += 1
                elif "assessment" in t or "qti" in t:
                    kinds["quizzes"] += 1
                elif "imsdt" in t:
                    kinds["discussions"] += 1
                elif "imswl" in t:
                    kinds["links"] += 1
                elif "assignment_settings" in hrefs or "learning-application" in t:
                    kinds["assignments"] += 1
                elif "web_resources/" in hrefs:
                    kinds["files"] += 1
                else:
                    kinds["other"] += 1
        return {"modules": [m.label + (f" – {m.title}" if m.title and m.title != m.label else "") for m in mods],
                "items": kinds, "resources": len(keep),
                "media": sum(1 for f in files if f.startswith("web_resources/")),
                "files": len(files), "warnings": warnings}


def validate(data: bytes) -> list[str]:
    """Problems that would break the import."""
    errs = []
    z = zipfile.ZipFile(io.BytesIO(data))
    names = set(z.namelist())
    try:
        root = etree.fromstring(z.read("imsmanifest.xml"))
    except Exception as e:  # noqa
        return [f"Manifest cannot be read: {e}"]
    ids = {r.get("identifier") for r in root.iter() if local(r.tag) == "resource"}
    for e in root.iter():
        if local(e.tag) == "file" and e.get("href") and e.get("href") not in names:
            errs.append(f"Declared file missing: {e.get('href')}")
        if local(e.tag) in ("item", "dependency") and e.get("identifierref") and e.get("identifierref") not in ids:
            errs.append(f"{local(e.tag)} points to missing resource {e.get('identifierref')}")
    return errs


def split(path_or_bytes, choose=None, combined=False):
    """Yield (file name, bytes, info) for each chosen module (or one combined package)."""
    c = Course(path_or_bytes)
    mods = c.modules if not choose else [m for m in c.modules if m.index in choose]
    if not mods:
        raise ValueError("No modules found / selected.")
    groups = [mods] if combined else [[m] for m in mods]
    used = set()
    for g in groups:
        name = ("Modules_" + "_".join(str(m.number or m.index) for m in g)) if combined else g[0].file_stem
        base, k = name, 2
        while name in used:
            name, k = f"{base}_{k}", k + 1
        used.add(name)
        data, info = c.build(g)
        info["errors"] = validate(data)
        yield f"{name}.imscc", data, info
