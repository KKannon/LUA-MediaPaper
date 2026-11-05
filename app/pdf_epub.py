"""Offline PDF to EPUB 3 converter. Rebuilds reflowable text; does not fetch resources or run scripts."""
import re
import statistics
import uuid
from datetime import datetime, timezone
from html import escape
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED
from PIL import Image as PILImage

MAX_PAGES = 1000
MAX_IMAGES = 400
MAX_IMAGE_PIXELS = 40_000_000
PAGES_PER_SECTION = 10

class InvalidPdf(ValueError):
    pass

def _clean(text):
    # Drop control characters that are invalid in XHTML.
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]', '', text)

def _join_lines(lines):
    text = ''
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if text.endswith('-') and line[:1].islower():
            text = text[:-1] + line  # Rejoin words hyphenated at the line break.
        elif text:
            text += ' ' + line
        else:
            text = line
    return re.sub(r'\s+', ' ', text).strip()

def _boxes(layout):
    """Text boxes and images of a page, top to bottom."""
    from pdfminer.layout import LTTextBox, LTTextLine, LTChar, LTImage, LTFigure
    items = []
    def sizes(box):
        for line in box:
            if isinstance(line, LTTextLine):
                for char in line:
                    if isinstance(char, LTChar) and char.get_text().strip():
                        yield char.size, 'bold' in (char.fontname or '').lower()
    def walk(node):
        for child in node:
            if isinstance(child, LTTextBox):
                chars = list(sizes(child))
                if not chars:
                    continue
                lines = [line.get_text() for line in child if isinstance(line, LTTextLine)]
                items.append({'kind': 'text', 'top': child.y1, 'x': child.x0, 'lines': lines,
                              'size': statistics.median(size for size, _ in chars), 'bold': sum(b for _, b in chars) > len(chars) / 2, 'chars': len(chars)})
            elif isinstance(child, LTImage):
                items.append({'kind': 'image', 'top': child.y1, 'x': child.x0, 'name': child.name, 'area': child.width * child.height})
            elif isinstance(child, LTFigure):
                walk(child)
    walk(layout)
    items.sort(key=lambda item: (-round(item['top']), item['x']))
    return items

def _page_images(page):
    """Decoded images of a pypdf page keyed by XObject name."""
    found = {}
    try:
        images = list(page.images)
    except Exception:
        return found
    for image in images:
        name = image.name.rsplit('.', 1)[0].lstrip('/')
        try:
            picture = image.image
            if picture is None or picture.width * picture.height > MAX_IMAGE_PIXELS or min(picture.size) < 24:
                continue
            buffer = BytesIO()
            if picture.mode in ('RGBA', 'LA', 'P'):
                picture.convert('RGBA').save(buffer, 'PNG', optimize=True)
                found[name] = (buffer.getvalue(), 'png')
            else:
                picture.convert('RGB').save(buffer, 'JPEG', quality=85, optimize=True)
                found[name] = (buffer.getvalue(), 'jpg')
        except Exception:
            continue  # Unsupported filters or damaged streams are skipped, not fatal.
    return found

def _outline(reader):
    """Top-level bookmarks as (page index, title)."""
    marks = []
    try:
        for item in reader.outline:
            if isinstance(item, list):
                continue
            try:
                index = reader.get_destination_page_number(item)
            except Exception:
                continue
            title = _clean(str(item.title or '')).strip()
            if title and index is not None and index >= 0:
                marks.append((index, title[:200]))
    except Exception:
        return []
    marks.sort()
    unique = []
    for index, title in marks:
        if not unique or unique[-1][0] != index:
            unique.append((index, title))
    return unique

def convert_pdf(data, title=None):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams
    from pdfminer.pdfdocument import PDFEncryptionError, PDFPasswordIncorrect
    from pdfminer.pdfparser import PDFSyntaxError
    if not data.startswith(b'%PDF-') and b'%PDF-' not in data[:1024]:
        raise InvalidPdf('O arquivo não é um PDF válido.')
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(''):
            raise InvalidPdf('Este PDF é protegido por senha. Use uma cópia sem proteção.')
        page_count = len(reader.pages)
    except InvalidPdf:
        raise
    except (PdfReadError, ValueError, KeyError) as exc:
        raise InvalidPdf('O arquivo não é um PDF válido.') from exc
    if not page_count:
        raise InvalidPdf('O PDF não tem páginas.')
    if page_count > MAX_PAGES:
        raise InvalidPdf(f'O PDF tem {page_count} páginas. O limite é {MAX_PAGES}.')
    metadata = reader.metadata or {}
    book_title = _clean((title or str(metadata.get('/Title') or '') or 'Livro').strip())[:200] or 'Livro'
    author = _clean(str(metadata.get('/Author') or '').strip())[:200]

    pages = []
    try:
        for index, layout in enumerate(extract_pages(BytesIO(data), laparams=LAParams(line_margin=0.5, boxes_flow=0.5))):
            pages.append(_boxes(layout))
    except (PDFEncryptionError, PDFPasswordIncorrect) as exc:
        raise InvalidPdf('Este PDF é protegido por senha. Use uma cópia sem proteção.') from exc
    except PDFSyntaxError as exc:
        raise InvalidPdf('O arquivo não é um PDF válido.') from exc

    # Body text size: the size carrying most characters. Larger text becomes headings.
    weights = {}
    for items in pages:
        for item in items:
            if item['kind'] == 'text':
                key = round(item['size'] * 2) / 2
                weights[key] = weights.get(key, 0) + item['chars']
    body = max(weights, key=weights.get) if weights else 11

    images, image_count = {}, 0
    rendered = []
    for index, items in enumerate(pages):
        decoded = _page_images(reader.pages[index]) if any(item['kind'] == 'image' for item in items) else {}
        parts = []
        for item in items:
            if item['kind'] == 'image':
                found = decoded.pop(item['name'], None)
                if found and image_count < MAX_IMAGES:
                    image_count += 1
                    name = f'images/img{image_count:04d}.{found[1]}'
                    images[name] = found[0]
                    parts.append(f'<figure><img src="../{name}" alt=""/></figure>')
                continue
            text = _clean(_join_lines(item['lines']))
            if not text or re.fullmatch(r'[\s.–—-]*(\d{1,4}|[ivxlc]{1,6}|[IVXLC]{1,6})[\s.–—-]*', text):
                continue  # Page numbers and empty boxes.
            if len(text) <= 160 and (item['size'] >= body * 1.25 or (item['bold'] and item['size'] >= body * 1.1 and len(text) <= 100)):
                level = 'h2' if item['size'] >= body * 1.6 else 'h3'
                parts.append(f'<{level}>{escape(text)}</{level}>')
            else:
                parts.append(f'<p>{escape(text)}</p>')
        # Images that pdfminer did not position (inline images, forms) go at the end of the page.
        for found in decoded.values():
            if image_count >= MAX_IMAGES:
                break
            image_count += 1
            name = f'images/img{image_count:04d}.{found[1]}'
            images[name] = found[0]
            parts.append(f'<figure><img src="../{name}" alt=""/></figure>')
        rendered.append(parts)

    if not any(rendered):
        raise InvalidPdf('Não foi encontrado texto nem imagens neste PDF.')

    # Sections follow the PDF bookmarks; without them, groups of pages.
    marks = _outline(reader)
    if marks and marks[0][0] > 0:
        marks.insert(0, (0, 'Início'))
    if not marks:
        marks = [(start, f'Páginas {start + 1}–{min(start + PAGES_PER_SECTION, page_count)}') for start in range(0, page_count, PAGES_PER_SECTION)]
    sections = []
    for number, (start, label) in enumerate(marks):
        end = marks[number + 1][0] if number + 1 < len(marks) else page_count
        body_parts = [part for parts in rendered[start:end] for part in parts]
        if body_parts:
            sections.append((label, body_parts))

    identifier = f'urn:uuid:{uuid.uuid4()}'
    modified = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('mimetype', 'application/epub+zip', compress_type=ZIP_STORED)
        archive.writestr('META-INF/container.xml', '<?xml version="1.0" encoding="UTF-8"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        archive.writestr('OEBPS/style.css', 'body{font-family:serif;line-height:1.5;margin:0 4%}p{margin:0 0 .8em;text-indent:1.2em;text-align:justify}h1,h2,h3{font-family:sans-serif;line-height:1.25;margin:1.4em 0 .6em;text-indent:0}figure{margin:1em 0;text-align:center}img{max-width:100%;height:auto}')
        manifest, spine, nav, ncx = [], [], [], []
        for number, (label, parts) in enumerate(sections, 1):
            name = f'text/section{number:04d}.xhtml'
            # Bookmarked chapters usually start with their own title; avoid printing it twice.
            heading = '' if re.fullmatch(r'<h[23]>(.*)</h[23]>', parts[0]) and re.fullmatch(r'<h[23]>(.*)</h[23]>', parts[0])[1].casefold() == escape(label).casefold() else f'<h1>{escape(label)}</h1>'
            archive.writestr('OEBPS/' + name, f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html>\n<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="pt-BR" lang="pt-BR"><head><title>{escape(label)}</title><link rel="stylesheet" type="text/css" href="../style.css"/></head><body><section>{heading}{"".join(parts)}</section></body></html>')
            manifest.append(f'<item id="s{number}" href="{name}" media-type="application/xhtml+xml"/>')
            spine.append(f'<itemref idref="s{number}"/>')
            nav.append(f'<li><a href="{name}">{escape(label)}</a></li>')
            ncx.append(f'<navPoint id="n{number}" playOrder="{number}"><navLabel><text>{escape(label)}</text></navLabel><content src="{name}"/></navPoint>')
        for number, (name, content) in enumerate(images.items(), 1):
            archive.writestr('OEBPS/' + name, content)
            kind = 'image/png' if name.endswith('.png') else 'image/jpeg'
            manifest.append(f'<item id="i{number}" href="{name}" media-type="{kind}"/>')
        archive.writestr('OEBPS/nav.xhtml', f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html>\n<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="pt-BR" lang="pt-BR"><head><title>Sumário</title></head><body><nav epub:type="toc" id="toc"><h1>Sumário</h1><ol>{"".join(nav)}</ol></nav></body></html>')
        archive.writestr('OEBPS/toc.ncx', f'<?xml version="1.0" encoding="UTF-8"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head><meta name="dtb:uid" content="{identifier}"/></head><docTitle><text>{escape(book_title)}</text></docTitle><navMap>{"".join(ncx)}</navMap></ncx>')
        creator = f'<dc:creator>{escape(author)}</dc:creator>' if author else ''
        archive.writestr('OEBPS/content.opf', f'<?xml version="1.0" encoding="UTF-8"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="pt-BR"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="bookid">{identifier}</dc:identifier><dc:title>{escape(book_title)}</dc:title>{creator}<dc:language>pt-BR</dc:language><meta property="dcterms:modified">{modified}</meta></metadata><manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/><item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/><item id="css" href="style.css" media-type="text/css"/>{"".join(manifest)}</manifest><spine toc="ncx">{"".join(spine)}</spine></package>')
    return output.getvalue()
