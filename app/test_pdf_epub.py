from io import BytesIO
from zipfile import ZipFile, ZIP_STORED
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, Client
from defusedxml import ElementTree as ET
from app.pdf_epub import convert_pdf, InvalidPdf

def sample_pdf(outline=True, encrypt=False):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    from PIL import Image
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4, encrypt='segredo' if encrypt else None)
    pdf.setTitle('Livro da Lua')
    pdf.setAuthor('Autora')
    picture = BytesIO()
    Image.new('RGB', (200, 120), '#a8c787').save(picture, 'PNG')
    for number, title in enumerate(('Capítulo Um', 'Capítulo Dois'), 1):
        if outline:
            pdf.bookmarkPage(f'c{number}')
            pdf.addOutlineEntry(title, f'c{number}', 0)
        pdf.setFont('Helvetica-Bold', 22)
        pdf.drawString(72, 760, title)
        pdf.setFont('Helvetica', 11)
        text = pdf.beginText(72, 720)
        for line in ('Era uma vez uma leitora que gostava de ca-', 'fé e de livros com acentuação: ação, coração.'):
            text.textLine(line)
        pdf.drawText(text)
        picture.seek(0)
        pdf.drawImage(ImageReader(picture), 72, 520, 200, 120)
        pdf.drawString(72, 480, 'Depois da imagem.')
        pdf.drawString(290, 40, str(number))
        pdf.showPage()
    pdf.save()
    return output.getvalue()

class PdfToEpubTests(SimpleTestCase):
    def read(self, epub):
        archive = ZipFile(BytesIO(epub))
        first = archive.infolist()[0]
        self.assertEqual((first.filename, first.compress_type), ('mimetype', ZIP_STORED))
        self.assertEqual(archive.read('mimetype'), b'application/epub+zip')
        for name in archive.namelist():
            if name.endswith(('.xhtml', '.opf', '.ncx', '.xml')):
                ET.fromstring(archive.read(name))
        return archive

    def test_chapters_follow_bookmarks_with_text_and_images(self):
        archive = self.read(convert_pdf(sample_pdf()))
        first = archive.read('OEBPS/text/section0001.xhtml').decode()
        self.assertIn('café e de livros com acentuação', first)
        self.assertLess(first.index('<img'), first.index('Depois da imagem.'))
        self.assertEqual(first.count('Capítulo Um'), 2)  # <title> and one heading, not repeated.
        self.assertNotIn('<p>1</p>', first)
        self.assertIn('Capítulo Dois', archive.read('OEBPS/nav.xhtml').decode())
        self.assertIn('<dc:title>Livro da Lua</dc:title>', archive.read('OEBPS/content.opf').decode())
        self.assertEqual(len([n for n in archive.namelist() if n.startswith('OEBPS/images/')]), 2)

    def test_without_bookmarks_pages_are_grouped(self):
        archive = self.read(convert_pdf(sample_pdf(outline=False), title='Outro título'))
        self.assertIn('Páginas 1–2', archive.read('OEBPS/nav.xhtml').decode())
        self.assertIn('<dc:title>Outro título</dc:title>', archive.read('OEBPS/content.opf').decode())

    def test_invalid_and_protected_files_are_rejected(self):
        for data in (b'not a pdf', b'%PDF-1.4 broken'):
            with self.assertRaises(InvalidPdf):
                convert_pdf(data)
        with self.assertRaisesRegex(InvalidPdf, 'senha'):
            convert_pdf(sample_pdf(encrypt=True))

    def test_api_requires_csrf_and_returns_epub(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post('/api/convert-pdf').status_code, 403)
        client.get('/api/status')
        token = client.cookies['csrftoken'].value
        self.assertEqual(client.post('/api/convert-pdf', {'file': SimpleUploadedFile('a.txt', b'x')}, HTTP_X_CSRFTOKEN=token).status_code, 400)
        response = client.post('/api/convert-pdf', {'file': SimpleUploadedFile('livro.pdf', sample_pdf())}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/epub+zip')
        self.assertIn('livro.epub', response['Content-Disposition'])
        self.assertEqual(self.client.get('/mais/pdf-epub').status_code, 200)
