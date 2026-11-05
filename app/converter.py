"""Offline EPUB renderer. Does not fetch resources or execute EPUB scripts/CSS."""
import posixpath
import warnings
from html import escape
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, BadZipFile
from urllib.parse import unquote
from defusedxml import ElementTree as ET
from bs4 import BeautifulSoup, NavigableString, Tag
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak
import reportlab

class InvalidEpub(ValueError):
    pass

def _fonts():
    if 'LuaVera' not in pdfmetrics.getRegisteredFontNames():
        directory = Path(reportlab.__file__).parent / 'fonts'
        for name, filename in [('LuaVera', 'Vera.ttf'), ('LuaVera-Bold', 'VeraBd.ttf'), ('LuaVera-Italic', 'VeraIt.ttf'), ('LuaVera-BoldItalic', 'VeraBI.ttf')]:
            pdfmetrics.registerFont(TTFont(name, str(directory / filename)))
        pdfmetrics.registerFontFamily('LuaVera', normal='LuaVera', bold='LuaVera-Bold', italic='LuaVera-Italic', boldItalic='LuaVera-BoldItalic')

def _inline(node):
    if isinstance(node, NavigableString):
        return escape(str(node))
    if not isinstance(node, Tag) or node.name in ('script', 'style', 'iframe', 'object', 'svg'):
        return ''
    content = ''.join(_inline(child) for child in node.children)
    if node.name == 'br':
        return '<br/>'
    tag = {'strong': 'b', 'b': 'b', 'em': 'i', 'i': 'i', 'sup': 'super', 'sub': 'sub', 'u': 'u'}.get(node.name)
    return f'<{tag}>{content}</{tag}>' if tag else content

def convert_epub(data, page_size='A4', font_size=11):
    _fonts()
    try:
        archive = ZipFile(BytesIO(data))
    except BadZipFile as exc:
        raise InvalidEpub('O arquivo não é um EPUB válido.') from exc
    with archive:
        entries = archive.infolist()
        if len(entries) > 4000 or sum(e.file_size for e in entries) > 150 * 1024 * 1024:
            raise InvalidEpub('O EPUB excede o limite descompactado de 150 MB / 4.000 arquivos.')
        if any(e.flag_bits & 1 for e in entries) or 'META-INF/encryption.xml' in archive.namelist():
            raise InvalidEpub('Este EPUB contém recursos criptografados. Use uma cópia sem proteção.')
        if any(e.file_size > 20 * 1024 * 1024 for e in entries):
            raise InvalidEpub('Um dos recursos do EPUB excede 20 MB.')
        try:
            container = ET.fromstring(archive.read('META-INF/container.xml'))
            rootfile = container.find('.//{*}rootfile').attrib['full-path']
            package = ET.fromstring(archive.read(rootfile))
            base = posixpath.dirname(rootfile)
            manifest = {item.attrib['id']: item.attrib for item in package.findall('.//{*}manifest/{*}item')}
            spine = [manifest[item.attrib['idref']] for item in package.findall('.//{*}spine/{*}itemref') if item.attrib.get('linear', 'yes') != 'no']
        except Exception as exc:
            raise InvalidEpub('O EPUB está incompleto ou tem uma estrutura inválida.') from exc
        if not spine:
            raise InvalidEpub('O EPUB não possui capítulos para converter.')
        def resource(directory, href):
            if ':' in href or href.startswith('/'):
                raise KeyError(href)
            return archive.read(posixpath.normpath(posixpath.join(directory, unquote(href.split('#')[0]))))
        pages = A4 if page_size == 'A4' else letter
        width, height = pages[0] - 100, pages[1] - 110
        normal = ParagraphStyle('body', fontName='LuaVera', fontSize=font_size, leading=font_size * 1.55, spaceAfter=9, alignment=TA_JUSTIFY, splitLongWords=True)
        heading = ParagraphStyle('heading', parent=normal, fontName='LuaVera-Bold', fontSize=font_size * 1.65, leading=font_size * 2, spaceBefore=12, spaceAfter=14, keepWithNext=True, alignment=0)
        story = []
        for chapter in spine:
            if chapter.get('media-type') not in ('application/xhtml+xml', 'text/html'):
                continue
            try:
                source = resource(base, chapter['href'])
            except KeyError as exc:
                raise InvalidEpub('Um capítulo referenciado não foi encontrado no EPUB.') from exc
            soup = BeautifulSoup(source, 'html.parser')
            for unwanted in soup(['script', 'style', 'iframe', 'object']):
                unwanted.decompose()
            body = soup.body or soup
            chapter_story = []
            chapter_dir = posixpath.dirname(posixpath.join(base, unquote(chapter['href'])))
            def walk(node):
                if isinstance(node, NavigableString):
                    if str(node).strip():
                        chapter_story.append(Paragraph(escape(str(node)), normal))
                    return
                if not isinstance(node, Tag):
                    return
                if node.name == 'img':
                    try:
                        raw = resource(chapter_dir, node.get('src', ''))
                        with warnings.catch_warnings():
                            warnings.simplefilter('error', PILImage.DecompressionBombWarning)
                            with PILImage.open(BytesIO(raw)) as picture:
                                if picture.width * picture.height > 20_000_000:
                                    raise ValueError('Image too large')
                                picture.convert('RGB').save(buffer := BytesIO(), format='PNG')
                        buffer.seek(0)
                        image = Image(buffer)
                        ratio = min(width / image.imageWidth, (height - 40) / image.imageHeight, 1)
                        image.drawWidth, image.drawHeight = image.imageWidth * ratio, image.imageHeight * ratio
                        chapter_story.extend([image, Spacer(1, 12)])
                    except Exception:
                        alt = node.get('alt', '').strip()
                        if alt:
                            chapter_story.append(Paragraph(escape(alt), normal))
                elif node.name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'blockquote', 'pre', 'td', 'th') and not node.find(['p', 'div', 'ul', 'ol', 'table']):
                    text = _inline(node).strip()
                    if text:
                        chapter_story.append(Paragraph(('• ' if node.name == 'li' else '') + text, heading if node.name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6') else normal))
                    for img in node.find_all('img'):
                        walk(img)
                else:
                    for child in node.children:
                        walk(child)
            walk(body)
            if chapter_story:
                if story:
                    story.append(PageBreak())
                story.extend(chapter_story)
        if not story:
            raise InvalidEpub('Nenhum conteúdo legível foi encontrado no EPUB.')
        title_element = package.find('.//{*}metadata/{*}title')
        title = title_element.text if title_element is not None else 'Livro'
        output = BytesIO()
        def footer(canvas, doc):
            canvas.saveState()
            canvas.setFont('LuaVera', 8)
            canvas.setFillColor(colors.HexColor('#666666'))
            canvas.drawRightString(pages[0] - 50, 30, str(doc.page))
            canvas.restoreState()
        SimpleDocTemplate(output, pagesize=pages, leftMargin=50, rightMargin=50, topMargin=50, bottomMargin=55, title=title, author='Lua MediaPaper').build(story, onFirstPage=footer, onLaterPages=footer)
        return output.getvalue()
