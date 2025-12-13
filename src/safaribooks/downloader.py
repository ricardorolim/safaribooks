import os
import sys
from multiprocessing import Process, Queue
from typing import Any
from urllib.parse import urljoin

from lxml import html

import safaribooks.urls as urls
from safaribooks.authentication import Authenticator
from safaribooks.epub import EPub
from safaribooks.logger import Logger
from safaribooks.oreilly import OreillyParser
from safaribooks.project_root import project_root
from safaribooks.toc import TableOfContents

COOKIES_FILE = "cookies.json"

LOGIN_URL = f"https://www.{urls.ORLY_DOMAIN}/member/login/"
LOGIN_ENTRY_URL = urls.SAFARI_BASE_URL + "/login/unified/?next=/home/"
API_TEMPLATE = urls.SAFARI_BASE_URL + "/api/v1/book/{0}/"

BASE_01_HTML = (
    "<!DOCTYPE html>\n"
    '<html lang="en" xml:lang="en" xmlns="http://www.w3.org/1999/xhtml"'
    ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
    ' xsi:schemaLocation="http://www.w3.org/2002/06/xhtml2/'
    ' http://www.w3.org/MarkUp/SCHEMA/xhtml2.xsd"'
    ' xmlns:epub="http://www.idpf.org/2007/ops">\n'
    "<head>\n"
    "{0}\n"
    '<style type="text/css">'
    "body{{margin:1em;background-color:transparent!important;}}"
    "#sbo-rt-content *{{text-indent:0pt!important;}}#sbo-rt-content .bq{{margin-right:1em!important;}}"
)

KINDLE_HTML = (
    "#sbo-rt-content *{{word-wrap:break-word!important;"
    "word-break:break-word!important;}}#sbo-rt-content table,#sbo-rt-content pre"
    "{{overflow-x:unset!important;overflow:unset!important;"
    "overflow-y:unset!important;white-space:pre-wrap!important;}}"
)

BASE_02_HTML = "</style></head>\n<body>{1}</body>\n</html>"


Chapter = dict[str, Any]


class Downloader:
    def __init__(self, args, book_id: int) -> None:
        self.args = args
        self.book_id = book_id
        self.logger = Logger("info_%s.log" % self.book_id, COOKIES_FILE)
        self.epub = EPub(self.logger)
        self.parser: OreillyParser | None = None
        self.css = []
        self.skipped_chapter_download = False
        self.created_chapter_directory = False

    def download(self):
        self.css_path = ""
        self.images_path = ""
        self.chapter_stylesheets = []
        self.css.clear()
        self.images = []
        self.api_url = API_TEMPLATE.format(self.book_id)
        self.base_html = (
            BASE_01_HTML + (KINDLE_HTML if not self.args.kindle else "") + BASE_02_HTML
        )

        self.logger.intro()
        authenticator = Authenticator(self.logger)
        self.session = authenticator.login(COOKIES_FILE)

        self.logger.info("Retrieving book info...")
        book_info = self.get_book_info()
        self.logger.book_info(book_info)

        self.logger.info("Retrieving book chapters...")
        book_chapters = self.get_book_chapters()

        if len(book_chapters) > sys.getrecursionlimit():
            sys.setrecursionlimit(len(book_chapters))

        clean_book_title = "".join(
            self.escape_dirname(book_info["title"]).split(",")[:2]
        ) + " ({0})".format(self.book_id)

        books_dir = os.path.join(project_root(), "Books")
        if not os.path.isdir(books_dir):
            os.mkdir(books_dir)

        book_path = os.path.join(books_dir, clean_book_title)
        self.create_book_dirs(book_path)

        self.logger.set_output_dir(book_path)
        self.logger.info(
            "Downloading book contents... (%s chapters)" % len(book_chapters),
            state=True,
        )

        book_base_url = book_info["web_url"]
        self.parser = OreillyParser(self.logger, book_base_url, self.book_id)
        cover = self.download_chapters(book_chapters, book_path)

        if not cover:
            cover, book_chapters = self.create_default_cover(
                book_chapters, book_info, book_path
            )

        self.css_done_queue = Queue(0) if "win" not in sys.platform else WinQueue()
        self.logger.info(
            "Downloading book CSSs... (%s files)" % len(self.css), state=True
        )
        self.collect_css(book_path)

        self.images_done_queue = Queue(0) if "win" not in sys.platform else WinQueue()
        self.logger.info(
            "Downloading book images... (%s files)" % len(self.images), state=True
        )
        self.collect_images(book_path)

        toc = self.download_toc()

        self.logger.info("Creating EPUB file...", state=True)
        self.epub.create_epub(
            book_path=book_path,
            book_id=self.book_id,
            toc=toc,
            book_info=book_info,
            css_path=self.css_path,
            images_path=self.images_path,
            book_chapters=book_chapters,
            cover=cover,
        )

        if self.args.no_cookies:
            os.remove(COOKIES_FILE)
        else:
            self.session.save_cookies(COOKIES_FILE)

        self.logger.done(os.path.join(book_path, str(self.book_id) + ".epub"))
        self.logger.unregister()

        if not self.logger.in_error and not self.args.log:
            os.remove(self.logger.log_file)

    def create_default_cover(
        self, book_chapters: list[Chapter], book_info, book_path: str
    ) -> tuple[str, list[Chapter]]:
        cover = self.get_default_cover(book_info)

        assert self.parser is not None
        parsed_html = self.parser.parse_html(
            html.fromstring(
                '<div id="sbo-rt-content"><img src="Images/{0}"></div>'.format(cover)
            ),
            is_first_page=True,
            html_filename="",
            chapter_title="",
            chapter_stylesheets=[],
            css_list=self.css,
        )

        book_chapters = [
            {"filename": "default_cover.xhtml", "title": "Cover"}
        ] + book_chapters

        filename = book_chapters[0]["filename"]
        self.save_page_html(
            book_path, filename, parsed_html.page_css, parsed_html.xhtml
        )

        assert parsed_html.cover_url
        return parsed_html.cover_url, book_chapters

    def get_book_info(self) -> dict[str, Any]:
        response = self.session.requests_provider(self.api_url)
        if not response:
            self.logger.exit("API: unable to retrieve book info.")

        book_info = response.json()
        if not isinstance(book_info, dict) or len(book_info.keys()) == 1:
            self.logger.exit(self.logger.api_error(book_info))

        if "last_chapter_read" in book_info:
            del book_info["last_chapter_read"]

        for key, value in book_info.items():
            if value is None:
                book_info[key] = "n/a"

        return book_info

    def get_book_chapters(self, page=1) -> list[Chapter]:
        response = self.session.requests_provider(
            urljoin(self.api_url, "chapter/?page=%s" % page)
        )
        if not response:
            self.logger.exit("API: unable to retrieve book chapters.")

        response = response.json()

        if not isinstance(response, dict) or len(response.keys()) == 1:
            self.logger.exit(self.logger.api_error(response))

        if not response.get("results"):
            self.logger.exit("API: unable to retrieve book chapters.")

        if response["count"] > sys.getrecursionlimit():
            sys.setrecursionlimit(response["count"])

        covers, rest = [], []
        for chapter in response["results"]:
            if "cover" in chapter["filename"] or "cover" in chapter["title"]:
                covers.append(chapter)
            else:
                rest.append(chapter)

        result = covers + rest
        return result + (self.get_book_chapters(page + 1) if response["next"] else [])

    def get_default_cover(self, book_info) -> str:
        if "cover" not in book_info:
            return "False"

        response = self.session.requests_provider(book_info["cover"], stream=True)
        if not response:
            self.logger.error(
                "Error trying to retrieve the cover: %s" % book_info["cover"]
            )
            return "False"

        file_ext = response.headers["Content-Type"].split("/")[-1]
        with open(
            os.path.join(self.images_path, "default_cover." + file_ext), "wb"
        ) as i:
            for chunk in response.iter_content(1024):
                i.write(chunk)

        return "default_cover." + file_ext

    def get_html(self, url: str, filename: str, chapter_title: str):
        response = self.session.requests_provider(url)
        if not response or response.status_code != 200:
            self.logger.exit(
                "Crawler: error trying to retrieve this page: %s (%s)\n    From: %s"
                % (filename, chapter_title, url)
            )

        try:
            return html.fromstring(response.text, base_url=urls.SAFARI_BASE_URL)
        except (html.etree.ParseError, html.etree.ParserError) as parsing_error:
            self.logger.error(parsing_error)
            self.logger.exit(
                "Crawler: error trying to parse this page: %s (%s)\n    From: %s"
                % (filename, chapter_title, url)
            )

    @staticmethod
    def escape_dirname(dirname, clean_space=False):
        if ":" in dirname:
            if dirname.index(":") > 15:
                dirname = dirname.split(":")[0]

            elif "win" in sys.platform:
                dirname = dirname.replace(":", ",")

        # fmt: off
        for ch in [ "~", "#", "%", "&", "*", "{", "}", "\\", "<", ">", "?", "/", "`", "'", '"', "|", "+", ":", ]:
        # fmt: on
            if ch in dirname:
                dirname = dirname.replace(ch, "_")

        return dirname if not clean_space else dirname.replace(" ", "")

    def create_book_dirs(self, book_path: str):
        if os.path.isdir(book_path):
            self.logger.log("Book directory already exists: %s" % book_path)

        else:
            os.makedirs(book_path)

        oebps = os.path.join(book_path, "OEBPS")
        if not os.path.isdir(oebps):
            self.created_chapter_directory = True
            os.makedirs(oebps)

        self.css_path = os.path.join(oebps, "Styles")
        if os.path.isdir(self.css_path):
            self.logger.log("CSSs directory already exists: %s" % self.css_path)

        else:
            os.makedirs(self.css_path)
            self.logger.css_ad_info.value = 1

        self.images_path = os.path.join(oebps, "Images")
        if os.path.isdir(self.images_path):
            self.logger.log("Images directory already exists: %s" % self.images_path)

        else:
            os.makedirs(self.images_path)
            self.logger.images_ad_info.value = 1

    def save_page_html(self, book_path: str, filename, css, xhtml):
        filename = filename.replace(".html", ".xhtml")
        open(os.path.join(book_path, "OEBPS", filename), "wb").write(
            self.base_html.format(css, xhtml).encode("utf-8", "xmlcharrefreplace")
        )
        self.logger.log("Created: %s" % filename)

    def download_chapters(
        self, book_chapters: list[Chapter], book_path: str
    ) -> str | None:
        book_cover = None

        for i, chapter in enumerate(book_chapters):
            chapter_filename = chapter["filename"]

            self.extract_images(chapter)
            self.extract_stylesheets(chapter)

            if not self.chapter_file_exists(book_path, chapter_filename):
                is_first_page = i == 0
                chapter_title = chapter["title"]

                chapter_html = self.get_html(
                    chapter["content"], chapter_filename, chapter_title
                )
                assert self.parser is not None
                parsed_html = self.parser.parse_html(
                    chapter_html,
                    is_first_page,
                    chapter_filename,
                    chapter_title,
                    self.chapter_stylesheets,
                    self.css,
                )

                book_cover = parsed_html.cover_url

                self.save_page_html(
                    book_path=book_path,
                    filename=chapter_filename,
                    css=parsed_html.page_css,
                    xhtml=parsed_html.xhtml,
                )
            elif (
                not self.created_chapter_directory and not self.skipped_chapter_download
            ):
                self.logger.info(
                    (
                        "File `%s` already exists.\n"
                        "    If you want to download again all the book,\n"
                        "    please delete the output directory '"
                        + book_path
                        + "' and restart the program."
                    )
                    % chapter_filename.replace(".html", ".xhtml")
                )
                self.skipped_chapter_download = True

            self.logger.state(len(book_chapters), i + 1)

        return book_cover

    def api_v2(self, chapter: Chapter) -> bool:
        return "v2" in chapter["content"]

    def extract_images(self, chapter: Chapter) -> None:
        asset_base_url = chapter["asset_base_url"]
        if self.api_v2(chapter):
            asset_base_url = (
                urls.SAFARI_BASE_URL
                + f"/api/v2/epubs/urn:orm:book:{self.book_id}/files"
            )

        for img_url in chapter.get("images", []):
            if self.api_v2(chapter):
                self.images.append(asset_base_url + "/" + img_url)
            else:
                self.images.append(urljoin(chapter["asset_base_url"], img_url))

    def extract_stylesheets(self, chapter: Chapter) -> None:
        self.chapter_stylesheets = [x["url"] for x in chapter.get("stylesheets", [])]
        self.chapter_stylesheets.extend(chapter.get("site_styles", []))

    def chapter_file_exists(self, book_path: str, chapter_filename: str) -> bool:
        return os.path.isfile(
            os.path.join(
                book_path, "OEBPS", chapter_filename.replace(".html", ".xhtml")
            )
        )

    def _thread_download_css(self, url, book_path: str):
        css_file = os.path.join(
            self.css_path, "Style{0:0>2}.css".format(self.css.index(url))
        )
        if os.path.isfile(css_file):
            if (
                not self.logger.css_ad_info.value
                and url not in self.css[: self.css.index(url)]
            ):
                self.logger.info(
                    (
                        "File `%s` already exists.\n"
                        "    If you want to download again all the CSSs,\n"
                        "    please delete the output directory '" + book_path + "'"
                        " and restart the program."
                    )
                    % css_file
                )
                self.logger.css_ad_info.value = 1

        else:
            response = self.session.requests_provider(url)
            if not response:
                self.logger.error(
                    "Error trying to retrieve this CSS: %s\n    From: %s"
                    % (css_file, url)
                )
            else:
                with open(css_file, "wb") as f:
                    f.write(response.content)

        self.css_done_queue.put(1)
        self.logger.state(len(self.css), self.css_done_queue.qsize())

    def _thread_download_images(self, url, book_path: str):
        image_name = url.split("/")[-1]
        image_path = os.path.join(self.images_path, image_name)
        if os.path.isfile(image_path):
            if (
                not self.logger.images_ad_info.value
                and url not in self.images[: self.images.index(url)]
            ):
                self.logger.info(
                    (
                        "File `%s` already exists.\n"
                        "    If you want to download again all the images,\n"
                        "    please delete the output directory '" + book_path + "'"
                        " and restart the program."
                    )
                    % image_name
                )
                self.logger.images_ad_info.value = 1

        else:
            response = self.session.requests_provider(
                urljoin(urls.SAFARI_BASE_URL, url), stream=True
            )
            if not response:
                self.logger.error(
                    "Error trying to retrieve this image: %s\n    From: %s"
                    % (image_name, url)
                )
                return

            with open(image_path, "wb") as img:
                for chunk in response.iter_content(1024):
                    img.write(chunk)

        self.images_done_queue.put(1)
        self.logger.state(len(self.images), self.images_done_queue.qsize())

    def _start_multiprocessing(self, operation, full_queue):
        if len(full_queue) > 5:
            for i in range(0, len(full_queue), 5):
                self._start_multiprocessing(operation, full_queue[i : i + 5])

        else:
            process_queue = [
                Process(target=operation, args=(arg,)) for arg in full_queue
            ]
            for proc in process_queue:
                proc.start()

            for proc in process_queue:
                proc.join()

    def collect_css(self, book_path: str):
        self.logger.state_status.value = -1

        # "self._start_multiprocessing" seems to cause problem. Switching to mono-thread download.
        for css_url in self.css:
            self._thread_download_css(css_url, book_path)

    def collect_images(self, book_path: str):
        if self.skipped_chapter_download:
            self.logger.info(
                "Some of the book contents were already downloaded.\n"
                "    If you want to be sure that all the images will be downloaded,\n"
                "    please delete the output directory '"
                + book_path
                + "' and restart the program."
            )

        self.logger.state_status.value = -1

        # "self._start_multiprocessing" seems to cause problem. Switching to mono-thread download.
        for image_url in self.images:
            self._thread_download_images(image_url, book_path)

    def download_toc(self) -> TableOfContents:
        response = self.session.requests_provider(urljoin(self.api_url, "toc/"))
        if not response:
            self.logger.exit(
                "API: unable to retrieve book chapters. "
                "Don't delete any files, just run again this program"
                " in order to complete the `.epub` creation!"
            )

        toc = response.json()

        if not isinstance(toc, list) and len(toc.keys()) == 1:
            self.logger.exit(
                self.logger.api_error(toc)
                + " Don't delete any files, just run again this program"
                " in order to complete the `.epub` creation!"
            )

        assert self.parser is not None
        navmap, children, depth = self.parser.parse_toc(toc)
        return TableOfContents(navmap, children, depth)


class WinQueue(
    list
):  # TODO: error while use `process` in Windows: can't pickle _thread.RLock objects
    def put(self, el):
        self.append(el)

    def qsize(self):
        return self.__len__()
