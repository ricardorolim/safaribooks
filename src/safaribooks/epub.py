import os
import shutil
from html import escape
from pathlib import Path

from lxml.html import HtmlElement

from safaribooks.display import Display
from safaribooks.toc import TableOfContents

PROJECT_ROOT = Path(__file__).parent.parent.parent

CONTAINER_XML = (
    '<?xml version="1.0"?>'
    '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
    "<rootfiles>"
    '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml" />'
    "</rootfiles>"
    "</container>"
)

# Format: ID, Title, Authors, Description, Subjects, Publisher, Rights, Date, CoverId, MANIFEST, SPINE, CoverUrl
CONTENT_OPF = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="2.0" >\n'
    '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" '
    ' xmlns:opf="http://www.idpf.org/2007/opf">\n'
    "<dc:title>{1}</dc:title>\n"
    "{2}\n"
    "<dc:description>{3}</dc:description>\n"
    "{4}"
    "<dc:publisher>{5}</dc:publisher>\n"
    "<dc:rights>{6}</dc:rights>\n"
    "<dc:language>en-US</dc:language>\n"
    "<dc:date>{7}</dc:date>\n"
    '<dc:identifier id="bookid">{0}</dc:identifier>\n'
    '<meta name="cover" content="{8}"/>\n'
    "</metadata>\n"
    "<manifest>\n"
    '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml" />\n'
    "{9}\n"
    "</manifest>\n"
    '<spine toc="ncx">\n{10}</spine>\n'
    '<guide><reference href="{11}" title="Cover" type="cover" /></guide>\n'
    "</package>"
)

# Format: ID, Depth, Title, Author, NAVMAP
TOC_NCX = (
    '<?xml version="1.0" encoding="utf-8" standalone="no" ?>\n'
    '<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN"'
    ' "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">\n'
    '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
    "<head>\n"
    '<meta content="ID:ISBN:{0}" name="dtb:uid"/>\n'
    '<meta content="{1}" name="dtb:depth"/>\n'
    '<meta content="0" name="dtb:totalPageCount"/>\n'
    '<meta content="0" name="dtb:maxPageNumber"/>\n'
    "</head>\n"
    "<docTitle><text>{2}</text></docTitle>\n"
    "<docAuthor><text>{3}</text></docAuthor>\n"
    "<navMap>{4}</navMap>\n"
    "</ncx>"
)


class EPub:
    def __init__(self, display: Display) -> None:
        self.display = display

    def create_epub(
        self,
        book_path: str,
        book_id: str,
        toc: TableOfContents,
        book_info,
        book_title,
        css_path,
        images_path,
        book_chapters,
        cover,
    ):
        open(os.path.join(book_path, "mimetype"), "w").write("application/epub+zip")
        meta_info = os.path.join(book_path, "META-INF")
        if os.path.isdir(meta_info):
            self.display.log("META-INF directory already exists: %s" % meta_info)
        else:
            os.makedirs(meta_info)

        open(os.path.join(meta_info, "container.xml"), "wb").write(
            CONTAINER_XML.encode("utf-8", "xmlcharrefreplace")
        )
        _, _, content = self.create_content_opf(
            css_path,
            images_path,
            book_chapters,
            book_info,
            book_id,
            book_title,
            cover,
        )

        open(os.path.join(book_path, "OEBPS", "content.opf"), "wb").write(
            content.encode("utf-8", "xmlcharrefreplace")
        )

        open(os.path.join(book_path, "OEBPS", "toc.ncx"), "wb").write(
            self.create_toc(toc, book_info, book_id, book_title).encode(
                "utf-8", "xmlcharrefreplace"
            )
        )

        zip_file = os.path.join(PROJECT_ROOT, "Books", book_id)
        if os.path.isfile(zip_file + ".zip"):
            os.remove(zip_file + ".zip")

        shutil.make_archive(zip_file, "zip", book_path)
        os.rename(zip_file + ".zip", os.path.join(book_path, book_id) + ".epub")

    def create_content_opf(
        self,
        css_path: str,
        images_path: str,
        book_chapters: list[HtmlElement],
        book_info: HtmlElement,
        book_id: str,
        book_title: str,
        cover: str,
    ) -> tuple[list[str], list[str], str]:
        css = next(os.walk(css_path))[2]
        images = next(os.walk(images_path))[2]

        manifest = []
        spine = []
        for chapter in book_chapters:
            chapter["filename"] = chapter["filename"].replace(".html", ".xhtml")
            item_id = escape("".join(chapter["filename"].split(".")[:-1]))
            manifest.append(
                '<item id="{0}" href="{1}" media-type="application/xhtml+xml" />'.format(
                    item_id, chapter["filename"]
                )
            )
            spine.append('<itemref idref="{0}"/>'.format(item_id))

        for image in set(images):
            dot_split = image.split(".")
            head = "img_" + escape("".join(dot_split[:-1]))
            extension = dot_split[-1]
            manifest.append(
                '<item id="{0}" href="Images/{1}" media-type="image/{2}" />'.format(
                    head, image, "jpeg" if "jp" in extension else extension
                )
            )

        for i in range(len(css)):
            manifest.append(
                '<item id="style_{0:0>2}" href="Styles/Style{0:0>2}.css" '
                'media-type="text/css" />'.format(i)
            )

        authors = "\n".join(
            '<dc:creator opf:file-as="{0}" opf:role="aut">{0}</dc:creator>'.format(
                escape(aut.get("name", "n/d"))
            )
            for aut in book_info.get("authors", [])
        )

        subjects = "\n".join(
            "<dc:subject>{0}</dc:subject>".format(escape(sub.get("name", "n/d")))
            for sub in book_info.get("subjects", [])
        )

        return (
            css,
            images,
            CONTENT_OPF.format(
                (book_info.get("isbn", book_id)),
                escape(book_title),
                authors,
                escape(book_info.get("description", "")),
                subjects,
                ", ".join(
                    escape(pub.get("name", ""))
                    for pub in book_info.get("publishers", [])
                ),
                escape(book_info.get("rights", "")),
                book_info.get("issued", ""),
                cover,
                "\n".join(manifest),
                "\n".join(spine),
                book_chapters[0]["filename"].replace(".html", ".xhtml"),
            ),
        )

    def create_toc(
        self,
        toc: TableOfContents,
        book_info: HtmlElement,
        book_id: str,
        book_title: str,
    ) -> str:
        return TOC_NCX.format(
            book_info.get("isbn", book_id),
            toc.depth,
            book_title,
            ", ".join(aut.get("name", "") for aut in book_info.get("authors", [])),
            toc.navmap,
        )
