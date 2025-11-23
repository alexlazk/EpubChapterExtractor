# EPUB Chapter Extractor (GUI)

A small Python tool that extracts **chapters from EPUB books** and saves each chapter as a separate `.txt` file.
It includes a simple **Tkinter GUI** where you can:

* select an EPUB file,
* choose how strictly chapters are detected,
* optionally create a `.zip` with all exported chapter files.

This project is designed for people who want to work with chapter‑level text (e.g. for reading, analysis, or feeding into other tools/LLMs).

---

## Features

* 📚 **EPUB support (EPUB2 & EPUB3)**
  Works with books that use either `nav.xhtml` or `toc.ncx` as their table of contents.

* 🧠 **TOC‑based chapter detection**
  Uses the internal EPUB table of contents instead of guessing from file names.

* 🔍 **Heuristics for “real” chapters**

  * Detects numbered chapters like:

    * `Chapter 1: ...`, `Chapter One`, `Capítulo 3`, `1 Title`, `II Title`, `One Title`
  * Ignores front/back matter such as:

    * “Introduction”, “Preface”, “Foreword”, “Index”, “Notes”, “About the Author”, “Table of Contents”, etc.

* 📝 **Text extraction from content blocks**
  Reads text from `<p>`, `<li>`, `<blockquote>` **and `<div>`**, which covers most modern EPUB layouts (including PDF‑converted books).

* 🗂 **Clean output**

  * One `.txt` per chapter: `01_Chapter_1_Title.txt`, `02_Chapter_2_Title.txt`, …
  * Optional `.zip` with all chapter files.

* 🖱 **GUI for non‑technical users**
  No command‑line required. Just run the script, select an EPUB, and click a button.

---

## How it works (high‑level)

1. **Open EPUB as a ZIP archive**

   * Locate the OPF (`content.opf`, `OEBPS/content.opf`, or via `META-INF/container.xml`).

2. **Read manifest & spine**

   * Map EPUB resource IDs to XHTML files.
   * Use the spine to determine the **reading order**.

3. **Read the Table of Contents (TOC)**

   * For EPUB3: parse `nav.xhtml` and the `<nav epub:type="toc">` section.
   * For EPUB2: parse `toc.ncx` and its `<navPoint>` entries (including nested ones).
   * Build a list of TOC entries: *title → XHTML file → spine position*.

4. **Decide which TOC entries are “chapters”**

   * Mark entries as:

     * *numbered chapter* (e.g. `Chapter 3`, `1 Title`, `IV Something`, `One Day`),
     * *front/back matter* (introduction, index, notes, etc.),
     * *part* (e.g. `Part One`, `Part II`).
   * Depending on the detection mode (below), keep only those that look like actual chapters.

5. **Extract text for each chapter**

   * For each chosen TOC entry:

     * find its position in the spine,
     * read all content from that XHTML and subsequent files up to the next TOC entry,
     * extract text from `<p>`, `<li>`, `<blockquote>`, and `<div>`,
     * discard “chapters” that are too short (to avoid false positives like blank TOC pages or ads).

6. **Export**

   * Save each chapter as `<NN>_<safe_title>.txt` inside a `*_chapters` folder.
   * Optionally, compress all `.txt` files into a single `.zip`.

---

## Requirements

* Python **3.8+** (recommended 3.9+)
* Tkinter (comes bundled with most standard Python installations)
* [`beautifulsoup4`](https://pypi.org/project/beautifulsoup4/)

---

## Installation

Clone this repository:

```bash
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>
```

Install the Python dependency:

```bash
pip install beautifulsoup4
```

> 💡 You don’t need `ebooklib` or any extra EPUB library.
> The script works directly over the EPUB (ZIP) structure using the standard library plus BeautifulSoup.

---

## Usage

### 1. Start the GUI

From the project folder, run:

```bash
python epub_chapters_gui.py
```

You’ll see a window with:

* A field + **“Browse…”** button to choose an EPUB file.
* A **detection mode** dropdown (`auto`, `strict`, `loose`).
* A checkbox to **create a ZIP**.
* A button: **“Extract chapters”**.
* A status area showing progress and results.

### 2. Detection modes

The dropdown `Mode of detection` controls how aggressively the tool decides what counts as a “chapter”:

* **`auto` (recommended)**

  * If the TOC has **3 or more entries that look like numbered chapters**, only those are used.
  * Otherwise, it uses all TOC entries that are *not* clearly front/back matter.
  * Good balance for most narrative & non‑fiction books.

* **`strict`**

  * Only TOC entries that look like numbered or clearly structured chapters:

    * `Chapter 1`, `Chapter Two`, `1 Title`, `III Title`, `One Title`, etc.
  * Best when the TOC is clean and you want to avoid essays, parts, or sections being treated as chapters.

* **`loose`**

  * Takes *all* TOC entries that are not clearly front/back matter.
  * Useful for essay collections or books where each TOC entry is a meaningful unit, even if not numbered.

### 3. Output

After clicking **“Extract chapters”**:

* The script creates a folder next to your EPUB file:

  ```text
  <book-file-name>_chapters/
      01_Chapter_1_Title.txt
      02_Chapter_2_Title.txt
      ...
  ```

* Each `.txt` file starts with the chapter title, followed by the extracted text.

* If the *Create ZIP* checkbox is enabled, you also get:

  ```text
  <book-file-name>_chapters.zip
  ```

containing all the chapter `.txt` files.

---

## Example

Given an EPUB like:

* `Chapter 1: How to Jump Really High`
* `Chapter 2: How to Throw a Pool Party`
* …
* `Chapter 28: How to Dispose of This Book`

Using `mode = auto` will yield:

```text
How To..._chapters/
  01_Chapter_1_How_to_Jump_Really_High.txt
  02_Chapter_2_How_to_Throw_a_Pool_Party.txt
  ...
  28_Chapter_28_How_to_Dispose_of_This_Book.txt
```

---

## Configuration & tuning

You can tweak the behavior by editing a few constants at the top of `epub_chapters_gui.py`:

* **`MIN_CHARS_PER_CHAPTER`**
  Default: `2000`

  * Chapters with fewer characters than this are discarded as likely noise (TOC pages, ads, tiny blurbs, etc.).
  * If your chapters are very short (e.g. micro‑essays), consider lowering this threshold.

* **`FRONT_BACK_WORDS`**
  List of keywords that mark a TOC entry as “front/back matter” (not a chapter):
  `"introduction"`, `"index"`, `"notes"`, `"about the author"`, etc.
  You can add or remove entries according to your preferences.

---

## Limitations

* This tool relies heavily on the **table of contents (TOC)** being reasonably structured.

  * If an EPUB has no TOC, or a very poor one, detection may fail or group too much text together.
* Complex textbooks with many nested headings (sections, subsections) may require custom tuning.
* Some edge‑case EPUBs might:

  * put most text in non‑standard tags or containers,
  * have TOCs that don’t correspond cleanly to chapter boundaries.

Even in those cases, the default heuristics handle many real‑world books surprisingly well, especially narrative and non‑fiction EPUBs with a normal TOC.

---

## Development

The core logic lives in:

* **`parse_epub_toc_and_spine`** – reads OPF, manifest, and TOC.
* **`split_epub` / `split_epub_by_toc`** – decides which TOC entries are chapters and slices text by spine ranges.
* **`extract_text_from_xhtml`** – extracts text from XHTML files.
* **`run_gui`** – sets up and runs the Tkinter user interface.

If you want to add features (batch processing, CLI mode, logging, etc.), the easiest entry points are:

* exposing `split_epub()` as a command‑line tool, or
* adding a “Process folder of EPUBs” button to the GUI.

---

## License

Add your preferred license here, for example:

```text
MIT License
Copyright (c) 2025 <Your Name>
...
```

---

If you tell me the exact name of your repository and how you want to describe yourself (author, contact, etc.), I can tailor this README with those details filled in.
