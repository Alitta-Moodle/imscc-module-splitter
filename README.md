# IMSCC Module Splitter

Split a Canvas course export (`.imscc`) into **one package per module**.

Canvas's *Export Course Content* page exports the whole course as a single package, and it has no option to export one module at a time. This tool takes that full export and creates `Module_01.imscc`, `Module_02.imscc` and so on. Each one is a complete, importable Canvas package.

## Why it's useful
- **Large courses:** a full course export is often too large to upload or review at once, including in AI assistants such as Claude or ChatGPT. A single module is small enough to upload, review or check on its own.
- **Review and UAT one module at a time:** compare, check and sign off each module separately.
- **Moving modules:** import just the modules you need into another course.

> Course content often belongs to a client or institution. Check your organisation's policy before uploading any course package to an online AI tool.

## What each module package contains
- **The module itself:** its items, text headers and settings. Prerequisites that point to other modules are removed, so the import doesn't fail.
- **Its content:** every page, assignment, quiz (including its question file), discussion and link in the module.
- **Its files:** every image and file those items use (`$IMS-CC-FILEBASE$` paths and file links).
- **Course settings:** the `course_settings` folder, which Canvas needs for the import.
- **Nothing else:** no content from other modules. Links to pages in other modules are listed as notes.

The tool checks each package after building it. **Valid package** means every declared file is present and every module item resolves.

## Install
1. Install [Python 3.10+](https://www.python.org/downloads/). On Windows, tick **Add Python to PATH**.
2. Download this repository (green **Code** button → **Download ZIP**) and unzip it.

## Use: web page
- **Windows:** double-click `run.bat`.
- **Mac/Linux:** run `./run.sh`.

The page opens at http://127.0.0.1:5054.

1. Choose the course export (`.imscc`), then click **Read modules**.
2. Tick the modules you want. Choose **One package per module** or **One package with all ticked modules**.
3. Click **Create packages**, then download each package or all of them as one zip.

Everything runs on your own computer. Nothing is uploaded anywhere.

## Use: command line
```
pip install -r requirements.txt
python cli.py course.imscc --list                          # show the modules
python cli.py course.imscc --out modules                   # one package per module
python cli.py course.imscc --modules 2,3 --out modules     # only these (numbers from --list)
python cli.py course.imscc --modules 2,3 --combined --out modules   # one package with both
```

Try it on the made-up example course: `python cli.py examples/sample_course.imscc --list`

## Get a course export from Canvas
Course › Settings › **Export Course Content** › **Course** › **Create Export**, then download the `.imscc` file.

## Import a module package into Canvas
Course › Settings › **Import Course Content** › **Canvas Course Export Package** › **Select specific content**, then tick the module.

## Limitations
- **Module names:** module numbers come from titles such as "Module 5: …". Modules without a number are named after their title.
- **Course-level content:** files or pages that aren't in any module are not included.
- **Testing:** the tool has been tested on Canvas common-cartridge exports. Other LMS exports may need changes.

## License
MIT – see [LICENSE](LICENSE).
