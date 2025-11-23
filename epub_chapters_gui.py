import os
import re
import zipfile
import xml.etree.ElementTree as ET
import posixpath
import urllib.parse
import statistics
from pathlib import Path
from typing import List, Dict, Any

from bs4 import BeautifulSoup

import tkinter as tk
from tkinter import filedialog, messagebox


# ===================== Configuración y heurísticas =====================

FRONT_BACK_WORDS = {
    'epigraph',
    'introduction',
    'preface',
    'foreword',
    'acknowledgments',
    'acknowledgements',
    'acknowledgment',
    'prologue',
    'epilogue',
    'about the author',
    'about the authors',
    'index',
    'contents',
    'table of contents',
    'cover',
    'title page',
    'copyright',
    'dedication',
    "author's note",
    "author’s note",
    'further reading',
    'notes',
    'endnotes',
    'footnotes',
    'appendix',
    'bibliography',
    'recipe',
    'recipes',
    'discover more',
    'also by',
}

NUMBER_WORDS_EN = {
    'one', 'two', 'three', 'four', 'five', 'six',
    'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve',
    'thirteen', 'fourteen', 'fifteen', 'sixteen',
    'seventeen', 'eighteen', 'nineteen', 'twenty',
}

# Mínimo de caracteres para considerar que un “capítulo” es real
MIN_CHARS_PER_CHAPTER = 2000


def normalize(s: str) -> str:
    return " ".join(s.lower().split())


def is_definitely_not_chapter(title: str) -> bool:
    """
    True si parece claramente front/back matter (índice, notas, acknowledgments…)
    NUNCA marca como falso algo que empiece por 'Chapter...' o 'Capítulo...'.
    """
    t = normalize(title)

    if t.startswith('chapter') or t.startswith('capítulo') or t.startswith('capitulo'):
        return False

    for bad in FRONT_BACK_WORDS:
        if t == bad:
            return True
        if t.startswith(bad + ':') or t.startswith(bad + ' '):
            return True
        if t.startswith('the ' + bad):
            return True

    return False


def is_roman_token(token: str) -> bool:
    core = re.sub(r'[^a-zA-Z]', '', token).lower()
    if not core or core == 'i':
        return False
    return bool(re.fullmatch(r'[ivxlcdm]+', core))


def looks_like_numbered_chapter(title: str) -> bool:
    """
    Detecta capítulos numerados del estilo:
      - 'Chapter 1: ...', 'Chapter Two: ...'
      - 'Capítulo 3 ...'
      - '1. Algo', 'II Algo', 'One Algo' (si no es front/back).
    """
    t = normalize(title)

    # 'Chapter 1', 'Capítulo 3', 'Chapter One'
    if re.match(r'^(chapter|cap[ií]tulo)\s+\w+', t, re.IGNORECASE):
        return True

    tokens = t.split()
    if not tokens:
        return False

    first = tokens[0]

    # '1 Algo', '2.Algo'
    if re.match(r'\d+', first):
        if not is_definitely_not_chapter(title):
            return True

    # 'IV Algo'
    if is_roman_token(first):
        if not is_definitely_not_chapter(title):
            return True

    # 'One Algo', 'Two Algo', etc.
    if first.rstrip(':.') in NUMBER_WORDS_EN:
        if not is_definitely_not_chapter(title):
            return True

    return False


def looks_like_part(title: str) -> bool:
    """
    Detecta 'Part One', 'Part I', 'Part 3: ...' etc.
    """
    t = normalize(title)
    return t.startswith('part ')


# ===================== Lectura OPF + TOC (nav.xhtml / toc.ncx) =====================

def find_opf_path(zf: zipfile.ZipFile) -> str:
    """
    Localiza el archivo .opf dentro del EPUB.
    """
    try:
        container_xml = zf.read('META-INF/container.xml')
        container = ET.fromstring(container_xml)
        rootfile_el = container.find('.//{*}rootfile')
        return rootfile_el.attrib['full-path']
    except Exception:
        # Fallbacks típicos
        for cand in ['content.opf', 'OEBPS/content.opf']:
            if cand in zf.namelist():
                return cand
        # Último recurso: el primer .opf que encontremos
        for name in zf.namelist():
            if name.lower().endswith('.opf'):
                return name
    raise RuntimeError("No se encontró archivo OPF en el EPUB")


def parse_epub_toc_and_spine(epub_path: str):
    """
    Devuelve:
      - zf: ZipFile abierto
      - opf_dir: carpeta del OPF dentro del zip
      - id_to_href: id de manifest -> href XHTML
      - spine_ids: lista de idref en orden de lectura
      - entries: lista de entradas de TOC:
          {
            'title': str,
            'href': str,
            'id': str,
            'spine_index': int,
            'play_order': int (solo si viene de toc.ncx)
          }
    """
    zf = zipfile.ZipFile(epub_path, 'r')
    opf_rel_path = find_opf_path(zf)
    opf_xml = zf.read(opf_rel_path)
    root = ET.fromstring(opf_xml)
    ns = {'opf': 'http://www.idpf.org/2007/opf'}

    manifest_el = root.find('opf:manifest', ns)
    spine_el = root.find('opf:spine', ns)

    id_to_href = {item.attrib['id']: item.attrib['href'] for item in manifest_el}
    href_to_id = {href: id_ for id_, href in id_to_href.items()}
    spine_ids = [item.attrib['idref'] for item in spine_el]
    id_to_spine_index = {idref: idx for idx, idref in enumerate(spine_ids)}
    opf_dir = posixpath.dirname(opf_rel_path)

    entries: List[Dict[str, Any]] = []

    # --- EPUB3: nav.xhtml ---
    nav_items = [
        item for item in manifest_el
        if 'properties' in item.attrib and 'nav' in item.attrib['properties']
    ]

    if nav_items:
        nav_href = nav_items[0].attrib['href']
        nav_full = posixpath.join(opf_dir, nav_href) if opf_dir else nav_href
        nav_html = zf.read(nav_full).decode('utf-8', errors='ignore')
        soup = BeautifulSoup(nav_html, 'html.parser')
        toc_nav = soup.find('nav', attrs={'epub:type': 'toc'}) or soup.find('nav')

        if toc_nav:
            for a in toc_nav.find_all('a'):
                title = a.get_text(strip=True)
                href = a.get('href')
                if not href:
                    continue
                href_base = href.split('#')[0]
                idref = href_to_id.get(href_base)
                if idref is None:
                    alt1 = 'xhtml/' + href_base
                    alt2 = href_base.split('/', 1)[-1]
                    idref = href_to_id.get(alt1) or href_to_id.get(alt2)
                if idref is None:
                    continue
                spine_index = id_to_spine_index.get(idref)
                if spine_index is None:
                    continue

                entries.append({
                    'title': title,
                    'href': href_base,
                    'id': idref,
                    'spine_index': spine_index,
                })

    # --- EPUB2: toc.ncx (solo si nav.xhtml no aportó nada) ---
    if not entries:
        ncx_items = [
            item for item in manifest_el
            if item.attrib.get('media-type') == 'application/x-dtbncx+xml'
        ]
        if ncx_items:
            ncx_href = ncx_items[0].attrib['href']
            ncx_full = posixpath.join(opf_dir, ncx_href) if opf_dir else ncx_href
            ncx_xml = zf.read(ncx_full)
            ncx_ns = {'ncx': 'http://www.daisy.org/z3986/2005/ncx/'}
            ncx_root = ET.fromstring(ncx_xml)
            nav_map = ncx_root.find('ncx:navMap', ncx_ns)

            if nav_map is not None:
                # IMPORTANTE: todos los navPoint, incluidos los anidados (Part -> capítulos)
                for nav_point in nav_map.findall('.//ncx:navPoint', ncx_ns):
                    text_el = nav_point.find('ncx:navLabel/ncx:text', ncx_ns)
                    content_el = nav_point.find('ncx:content', ncx_ns)
                    if content_el is None:
                        continue
                    title = text_el.text if text_el is not None else ''
                    src = content_el.attrib.get('src', '')
                    if not src:
                        continue
                    href_base = src.split('#')[0]
                    idref = href_to_id.get(href_base)
                    if idref is None:
                        alt1 = 'text/' + href_base
                        alt2 = href_base.split('/', 1)[-1]
                        idref = href_to_id.get(alt1) or href_to_id.get(alt2)
                    if idref is None:
                        continue
                    spine_index = id_to_spine_index.get(idref)
                    if spine_index is None:
                        continue
                    play_order = int(nav_point.attrib.get('playOrder', '0') or 0)

                    entries.append({
                        'title': title,
                        'href': href_base,
                        'id': idref,
                        'spine_index': spine_index,
                        'play_order': play_order,
                    })

    entries.sort(key=lambda e: (e.get('play_order', 0), e['spine_index']))
    return zf, opf_dir, id_to_href, spine_ids, entries


# ===================== Extracción de texto de los XHTML =====================

def extract_text_from_xhtml(zf: zipfile.ZipFile, opf_dir: str, href: str) -> str:
    """
    Lee un XHTML del EPUB soportando:
      - rutas normales (OEBPS/...)
      - rutas con %xx (ej. %21 -> '!')
    y extrae texto de <p>, <li>, <blockquote> y <div>.
    Esto último es lo que hace que funcione bien con "How To".
    """
    paths_to_try = []

    full = posixpath.join(opf_dir, href) if opf_dir else href
    paths_to_try.append(full)
    paths_to_try.append(full.lstrip("/"))

    # Versión des-escapada del href (caso %21 -> !, etc.)
    unquoted_href = urllib.parse.unquote(href)
    if unquoted_href != href:
        full_unq = posixpath.join(opf_dir, unquoted_href) if opf_dir else unquoted_href
        paths_to_try.append(full_unq)
        paths_to_try.append(full_unq.lstrip("/"))

    # Versión des-escapada de la ruta completa
    full_unq2 = urllib.parse.unquote(full)
    paths_to_try.append(full_unq2)
    paths_to_try.append(full_unq2.lstrip("/"))

    # Quitar duplicados
    seen = set()
    ordered_paths = []
    for p in paths_to_try:
        if p not in seen:
            seen.add(p)
            ordered_paths.append(p)

    html = None
    for p in ordered_paths:
        try:
            html = zf.read(p)
            break
        except KeyError:
            continue

    if html is None:
        return ""

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()

    body = soup.body or soup
    texts = []

    # 👇 Aquí está el cambio importante: también leemos <div>
    for elem in body.find_all(["p", "li", "blockquote", "div"]):
        txt = elem.get_text(" ", strip=True)
        if txt:
            texts.append(txt)

    return "\n\n".join(texts)


# ===================== División en capítulos usando el TOC =====================

def split_epub_by_toc(epub_path: str, mode: str = "auto") -> List[Dict[str, Any]]:
    """
    Separa un EPUB en capítulos usando el TOC interno (nav.xhtml o toc.ncx).
    mode:
      - 'strict': solo entradas numeradas tipo capítulo.
      - 'loose' : todas las entradas que no sean front/back matter.
      - 'auto'  : si hay >=3 numeradas, usa solo esas; si no, usa 'loose'.
    """
    zf, opf_dir, id_to_href, spine_ids, entries = parse_epub_toc_and_spine(epub_path)
    if not entries:
        return []

    for e in entries:
        e["is_numbered"] = looks_like_numbered_chapter(e["title"])
        e["is_front_back"] = is_definitely_not_chapter(e["title"])
        e["is_part"] = looks_like_part(e["title"])

    # Elegimos qué entradas se considerarán capítulos
    if mode == "strict":
        chapter_entries = [e for e in entries if e["is_numbered"]]
    elif mode == "loose":
        chapter_entries = [e for e in entries if not e["is_front_back"]]
    else:  # auto
        strict_candidates = [e for e in entries if e["is_numbered"]]
        if len(strict_candidates) >= 3:
            chapter_entries = strict_candidates
        else:
            chapter_entries = [e for e in entries if not e["is_front_back"]]

    # Si en auto solo encontramos "Part 1, Part 2...", dejamos que otro
    # mecanismo se ocupe (si lo hubiera). De momento devolvemos vacío.
    if mode == "auto":
        if chapter_entries and all(e.get("is_part") and not e["is_numbered"] for e in chapter_entries):
            return []

    if not chapter_entries:
        return []

    chapters: List[Dict[str, Any]] = []
    seen_ranges = set()

    for entry in chapter_entries:
        start = entry["spine_index"]
        later_entries = [e for e in entries if e["spine_index"] > start]
        end = min(e["spine_index"] for e in later_entries) if later_entries else len(spine_ids)
        spine_range = (start, end)
        if spine_range in seen_ranges:
            continue

        text_parts = []
        for idx in range(start, end):
            idref = spine_ids[idx]
            href = id_to_href[idref]
            chunk = extract_text_from_xhtml(zf, opf_dir, href)
            if chunk.strip():
                text_parts.append(chunk)

        full_text = "\n\n".join(text_parts).strip()
        if not full_text:
            continue

        chapters.append({
            "title": entry["title"],
            "text": full_text,
            "spine_range": spine_range,
        })
        seen_ranges.add(spine_range)

    if not chapters:
        return []

    # Filtro por tamaño: primero algo razonable, luego por mediana si fuera necesario
    lengths = [len(ch["text"]) for ch in chapters]
    median = statistics.median(lengths) if lengths else 0

    long_chapters = [ch for ch in chapters if len(ch["text"]) >= MIN_CHARS_PER_CHAPTER]
    if long_chapters:
        filtered = long_chapters
    else:
        threshold = max(500, int(median // 4))
        filtered = [ch for ch in chapters if len(ch["text"]) >= threshold]

    filtered.sort(key=lambda c: c["spine_range"][0])
    for i, ch in enumerate(filtered, 1):
        ch["number"] = i

    return filtered


def split_epub(epub_path: str, mode: str = "auto") -> List[Dict[str, Any]]:
    """
    Punto de entrada principal: por ahora solo usamos el TOC.
    """
    return split_epub_by_toc(epub_path, mode=mode)


# ===================== Guardar capítulos en TXT + ZIP =====================

def save_chapters_to_txt_and_zip(epub_path: str, zip_too: bool = True, mode: str = "auto"):
    """
    Extrae capítulos, guarda cada uno en un .txt en una carpeta junto al EPUB,
    y opcionalmente crea también un .zip con todos.

    Devuelve: (chapters, out_dir, zip_path | None)
    """
    epub_path = os.path.abspath(epub_path)
    chapters = split_epub(epub_path, mode=mode)

    if not chapters:
        return [], None, None

    base_dir = os.path.dirname(epub_path)
    base_name = Path(epub_path).stem
    out_dir = os.path.join(base_dir, base_name + "_chapters")
    os.makedirs(out_dir, exist_ok=True)

    txt_paths = []

    for ch in chapters:
        num = ch["number"]
        title = ch["title"]
        safe_title = re.sub(r"[^a-zA-Z0-9_-]+", "_", title)[:60].strip("_")
        if not safe_title:
            safe_title = f"chapter_{num}"

        filename = os.path.join(out_dir, f"{num:02d}_{safe_title}.txt")
        with open(filename, "w", encoding="utf-8") as f:
            f.write(title + "\n\n")
            f.write(ch["text"])
        txt_paths.append(filename)

    zip_path = None
    if zip_too:
        zip_path = os.path.join(base_dir, base_name + "_chapters.zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for p in txt_paths:
                arcname = os.path.join(os.path.basename(out_dir), os.path.basename(p))
                z.write(p, arcname=arcname)

    return chapters, out_dir, zip_path


# ===================== GUI con Tkinter =====================

def run_gui():
    root = tk.Tk()
    root.title("EPUB → capítulos TXT")

    epub_path_var = tk.StringVar()
    mode_var = tk.StringVar(value="auto")   # auto / strict / loose
    zip_var = tk.BooleanVar(value=True)
    status_var = tk.StringVar(value="Selecciona un EPUB y pulsa «Extraer capítulos».")

    def choose_epub():
        filename = filedialog.askopenfilename(
            title="Selecciona un EPUB",
            filetypes=[("EPUB files", "*.epub"), ("Todos los archivos", "*.*")]
        )
        if filename:
            epub_path_var.set(filename)
            status_var.set(f"EPUB seleccionado:\n{filename}")

    def extract_chapters_gui():
        epub_path = epub_path_var.get().strip()
        if not epub_path:
            messagebox.showwarning("Falta archivo", "Primero selecciona un archivo EPUB.")
            return

        epub_path_obj = Path(epub_path)
        if not epub_path_obj.exists():
            messagebox.showerror("Error", "El archivo EPUB no existe.")
            return

        status_var.set("Extrayendo capítulos...")
        root.update_idletasks()

        try:
            chapters, out_dir_str, zip_path = save_chapters_to_txt_and_zip(
                str(epub_path_obj),
                zip_too=zip_var.get(),
                mode=mode_var.get(),
            )
        except Exception as e:
            messagebox.showerror("Error", f"Ocurrió un error procesando el EPUB:\n{e}")
            status_var.set("Error al procesar el EPUB.")
            return

        if not chapters:
            messagebox.showinfo(
                "Sin capítulos",
                "No se detectaron capítulos con la heurística actual.\n"
                "Prueba otro modo (strict/loose) o baja MIN_CHARS_PER_CHAPTER en el código."
            )
            status_var.set("No se detectaron capítulos.")
            return

        msg = f"Se extrajeron {len(chapters)} capítulos en:\n{out_dir_str}"
        if zip_path:
            msg += f"\n\nTambién se creó el ZIP:\n{zip_path}"

        messagebox.showinfo("Listo", msg)
        status_var.set(msg)

    frame = tk.Frame(root, padx=10, pady=10)
    frame.pack(fill="both", expand=True)

    # Fila 0: selección de archivo
    tk.Label(frame, text="Archivo EPUB:").grid(row=0, column=0, sticky="w")
    tk.Entry(frame, textvariable=epub_path_var, width=60).grid(
        row=0, column=1, padx=5, pady=5, sticky="we"
    )
    tk.Button(frame, text="Buscar...", command=choose_epub).grid(
        row=0, column=2, padx=5, pady=5
    )

    # Fila 1: modo de detección
    tk.Label(frame, text="Modo de detección:").grid(row=1, column=0, sticky="w")
    tk.OptionMenu(frame, mode_var, "auto", "strict", "loose").grid(
        row=1, column=1, sticky="w", padx=5, pady=5
    )

    # Fila 2: ZIP
    tk.Checkbutton(
        frame, text="Crear ZIP con los capítulos", variable=zip_var
    ).grid(row=2, column=1, sticky="w", padx=5, pady=5)

    # Fila 3: botón de acción
    tk.Button(
        frame,
        text="Extraer capítulos",
        command=extract_chapters_gui,
        width=20
    ).grid(row=3, column=1, pady=10)

    # Fila 4: estado
    tk.Label(frame, textvariable=status_var, justify="left", fg="gray").grid(
        row=4, column=0, columnspan=3, sticky="w", pady=5
    )

    frame.columnconfigure(1, weight=1)

    root.mainloop()


if __name__ == "__main__":
    run_gui()
