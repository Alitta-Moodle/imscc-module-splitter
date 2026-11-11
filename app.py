"""Local web page: http://127.0.0.1:5054"""
import io
import tempfile
import traceback
import uuid
import zipfile
from pathlib import Path

from flask import Flask, render_template, request, send_file

from splitter import Course, split

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024
WORK = Path(tempfile.gettempdir()) / "imscc_splitter"
WORK.mkdir(exist_ok=True)


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/load")
def load():
    try:
        f = request.files.get("imscc")
        if not f or not f.filename:
            raise ValueError("Choose the course export (.imscc).")
        job = uuid.uuid4().hex
        p = WORK / f"{job}.imscc"
        f.save(p)
        c = Course(str(p))
        if not c.modules:
            raise ValueError("No modules found in this export.")
        return render_template("index.html", job=job, src=f.filename, modules=c.modules)
    except Exception as e:
        return render_template("index.html", error=str(e), trace=traceback.format_exc()), 400


@app.post("/split")
def do_split():
    try:
        job = request.form["job"]
        src = WORK / f"{Path(job).name}.imscc"
        choose = {int(x) for x in request.form.getlist("m")}
        if not choose:
            raise ValueError("Tick at least one module.")
        combined = request.form.get("combined") == "1"
        results = []
        bundle = io.BytesIO()
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_STORED) as z:
            report = []
            for name, data, info in split(str(src), choose, combined):
                z.writestr(name, data)
                (WORK / f"{job}_{name}").write_bytes(data)
                results.append((name, info))
                report.append(f"{name}\n  " + ", ".join(f"{k}: {v}" for k, v in info["items"].items() if v)
                              + f"\n  media files: {info['media']}"
                              + "".join(f"\n  ERROR: {e}" for e in info["errors"])
                              + "".join(f"\n  note: {w}" for w in info["warnings"]))
            z.writestr("README.txt", "Import each package into Canvas with: Settings > Import Course Content > "
                       "Canvas Course Export Package > Select specific content.\n\n" + "\n\n".join(report))
        (WORK / f"{job}_all.zip").write_bytes(bundle.getvalue())
        c = Course(str(src))
        return render_template("index.html", job=job, src=request.form.get("src", ""), modules=c.modules,
                               results=results, chosen=choose)
    except Exception as e:
        return render_template("index.html", error=str(e), trace=traceback.format_exc()), 400


@app.get("/download/<job>/<name>")
def download(job, name):
    p = WORK / f"{Path(job).name}_{Path(name).name}"
    if not p.exists():
        return "Not found – run the split again.", 404
    dl = name if name != "all.zip" else "module_packages.zip"
    return send_file(p, as_attachment=True, download_name=dl)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5054, debug=False)
