import os
import sys
import re
import json
from typing import Any
import requests
from html import escape
from multiprocessing import Process, Queue
from urllib.parse import urljoin, urlparse, parse_qs, quote_plus
from safaribooks.logger import Logger
from lxml import html

from safaribooks.epub import EPub
from safaribooks.oreilly import Oreilly
from safaribooks.project_root import project_root
from safaribooks.toc import TableOfContents
import safaribooks.urls as urls

USE_PROXY = False
PROXIES = {"https": "https://127.0.0.1:8080"}
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

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": LOGIN_ENTRY_URL,
    "Upgrade-Insecure-Requests": "1",
    "User-Agent":   "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
}

COOKIE_FLOAT_MAX_AGE_PATTERN = re.compile(r"(max-age=\d*\.\d*)", re.IGNORECASE)

class Downloader:
    def __init__(self, args, book_id: str, cred: tuple[str, str]):
        self.args = args
        self.book_id = book_id
        self.cred = cred
        self.logger = Logger("info_%s.log" % escape(self.book_id), COOKIES_FILE)
        self.epub = EPub(self.logger)
        self.oreilly = Oreilly(self.logger)
        self.css = []

    def download(self):
        self.api_url = API_TEMPLATE.format(self.book_id)
        self.base_html = (
            BASE_01_HTML
            + (KINDLE_HTML if not self.args.kindle else "")
            + BASE_02_HTML
        )

        self.logger.intro()
        self.login()

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

        self.css_path = ""
        self.images_path = ""
        self.chapter_stylesheets = []
        self.css.clear()
        self.images = []

        base_url = book_info["web_url"]
        cover = self.download_chapters(book_chapters, book_path, base_url)

        if not cover:
            cover, book_chapters = self.create_default_cover(
                book_chapters, book_info, book_path, base_url
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
            book_title=book_info["title"],
            css_path=self.css_path,
            images_path=self.images_path,
            book_chapters=book_chapters,
            cover=cover,
        )

        if not self.args.no_cookies:
            json.dump(self.session.cookies.get_dict(), open(COOKIES_FILE, "w"))

        self.logger.done(os.path.join(book_path, self.book_id + ".epub"))
        self.logger.unregister()

        if not self.logger.in_error and not self.args.log:
            os.remove(self.logger.log_file)

    def create_default_cover(
        self, book_chapters, book_info, book_path: str, base_url: str
    ) -> tuple[str | None, list[dict[str, str]]]:
        cover = self.get_default_cover(book_info)
        parsed_html = self.oreilly.parse_html(
            html.fromstring(
                '<div id="sbo-rt-content"><img src="Images/{0}"></div>'.format(cover)
            ),
            True,
            html_filename="",
            chapter_title="",
            chapter_stylesheets=[],
            css_list=self.css,
            base_url=base_url,
            book_id=self.book_id,
        )

        book_chapters = [
            {"filename": "default_cover.xhtml", "title": "Cover"}
        ] + book_chapters

        filename = book_chapters[0]["filename"]
        self.save_page_html(
            book_path, filename, parsed_html.page_css, parsed_html.xhtml
        )

        return parsed_html.cover_url, book_chapters

    def login(self):
        self.session = requests.Session()
        if USE_PROXY:  # DEBUG
            self.session.proxies = PROXIES
            self.session.verify = False

        self.session.headers.update(HEADERS)

        self.jwt = {}

        if not self.cred:
            if not os.path.isfile(COOKIES_FILE):
                self.logger.exit(
                    "Login: unable to find `cookies.json` file.\n"
                    "    Please use the `--cred` or `--login` options to perform the login."
                )

            self.session.cookies.update(json.load(open(COOKIES_FILE)))

        else:
            self.logger.info("Logging into Safari Books Online...", state=True)
            self.do_login(*self.cred)
            if not self.args.no_cookies:
                json.dump(self.session.cookies.get_dict(), open(COOKIES_FILE, "w"))

        self.check_login()

    def handle_cookie_update(self, set_cookie_headers):
        for morsel in set_cookie_headers:
            # Handle Float 'max-age' Cookie
            if COOKIE_FLOAT_MAX_AGE_PATTERN.search(morsel):
                cookie_key, cookie_value = morsel.split(";")[0].split("=")
                self.session.cookies.set(cookie_key, cookie_value)

    def requests_provider(
        self, url, is_post=False, data=None, perform_redirect=True, **kwargs
    ) -> requests.Response | None:
        try:
            if is_post:
                response = self.session.post(
                    url, data=data, allow_redirects=False, **kwargs
                )
            else:
                response = self.session.get(
                    url, data=data, allow_redirects=False, **kwargs
                )

            self.handle_cookie_update(response.raw.headers.getlist("Set-Cookie"))

            self.logger.last_request = (
                url,
                data,
                kwargs,
                response.status_code,
                "\n".join(["\t{}: {}".format(*h) for h in response.headers.items()]),
                response.text,
            )

        except (
            requests.ConnectionError,
            requests.ConnectTimeout,
            requests.RequestException,
        ) as request_exception:
            self.logger.error(str(request_exception))
            return

        if response.is_redirect and perform_redirect:
            if not response.next:
                self.logger.error("Redirect expected but no redirect URL found")
                return

            return self.requests_provider(
                response.next.url, is_post, None, perform_redirect
            )
            # TODO: How about **kwargs?

        return response

    def do_login(self, email: str, password: str):
        response = self.requests_provider(LOGIN_ENTRY_URL)
        if not response:
            self.logger.exit(
                "Login: unable to reach Safari Books Online. Try again..."
            )

        next_parameter = None
        try:
            url = response.request.url
            if not url:
                self.logger.exit("Login: url not found in request")

            query = parse_qs(urlparse(url).query)
            next_parameter = query["next"][0]

        except (AttributeError, ValueError, IndexError):
            self.logger.exit(
                "Login: unable to complete login on Safari Books Online. Try again..."
            )

        redirect_uri = urls.API_ORIGIN_URL + quote_plus(next_parameter)

        response = self.requests_provider(
            LOGIN_URL,
            is_post=True,
            json={"email": email, "password": password, "redirect_uri": redirect_uri},
            perform_redirect=False,
        )

        if not response:
            self.logger.exit(
                "Login: unable to perform auth to Safari Books Online.\n    Try again..."
            )

        if response.status_code != 200:  # TODO: To be reviewed
            try:
                error_page = html.fromstring(response.text)
                errors_message = error_page.xpath("//ul[@class='errorlist']//li/text()")
                recaptcha = error_page.xpath("//div[@class='g-recaptcha']")
                messages = (
                    [
                        "    `%s`" % error
                        for error in errors_message
                        if "password" in error or "email" in error
                    ]
                    if errors_message
                    else []
                ) + (
                    ["    `ReCaptcha required (wait or do logout from the website).`"]
                    if recaptcha
                    else []
                )
                self.logger.exit(
                    "Login: unable to perform auth login to Safari Books Online.\n"
                    + self.logger.SH_YELLOW
                    + "[*]"
                    + self.logger.SH_DEFAULT
                    + " Details:\n"
                    + "%s"
                    % "\n".join(
                        messages if len(messages) else ["    Unexpected error!"]
                    )
                )
            except (html.etree.ParseError, html.etree.ParserError) as parsing_error:
                self.logger.error(parsing_error)
                self.logger.exit(
                    "Login: your login went wrong and it encountered in an error"
                    " trying to parse the login details of Safari Books Online. Try again..."
                )

        self.jwt = (
            response.json()
        )  # TODO: save JWT Tokens and use the refresh_token to restore user session
        response = self.requests_provider(self.jwt["redirect_uri"])
        if not response:
            self.logger.exit(
                "Login: unable to reach Safari Books Online. Try again..."
            )

    def check_login(self):
        response = self.requests_provider(urls.PROFILE_URL, perform_redirect=False)

        if not response:
            self.logger.exit(
                "Login: unable to reach Safari Books Online. Try again..."
            )

        elif response.status_code != 200:
            self.logger.exit("Authentication issue: unable to access profile page.")

        elif 'user_type":"Expired"' in response.text:
            self.logger.exit("Authentication issue: account subscription expired.")

        self.logger.info("Successfully authenticated.", state=True)

    def get_book_info(self) -> dict[str, Any]:
        response = self.requests_provider(self.api_url)
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

    def get_book_chapters(self, page=1):
        response = self.requests_provider(
            urljoin(self.api_url, "chapter/?page=%s" % page)
        )
        if not response:
            self.logger.exit("API: unable to retrieve book chapters.")

        response = response.json()

        if not isinstance(response, dict) or len(response.keys()) == 1:
            self.logger.exit(self.logger.api_error(response))

        if "results" not in response or not len(response["results"]):
            self.logger.exit("API: unable to retrieve book chapters.")

        if response["count"] > sys.getrecursionlimit():
            sys.setrecursionlimit(response["count"])

        covers, rest = [], []
        for c in response["results"]:
            if "cover" in c["filename"] or "cover" in c["title"]:
                covers.append(c)
            else:
                rest.append(c)

        result = covers + rest
        return result + (self.get_book_chapters(page + 1) if response["next"] else [])

    def get_default_cover(self, book_info) -> str | None:
        if "cover" not in book_info:
            return None

        response = self.requests_provider(book_info["cover"], stream=True)
        if not response:
            self.logger.error(
                "Error trying to retrieve the cover: %s" % book_info["cover"]
            )
            return None

        file_ext = response.headers["Content-Type"].split("/")[-1]
        with open(
            os.path.join(self.images_path, "default_cover." + file_ext), "wb"
        ) as i:
            for chunk in response.iter_content(1024):
                i.write(chunk)

        return "default_cover." + file_ext

    def get_html(self, url, filename, chapter_title: str):
        response = self.requests_provider(url)
        if not response or response.status_code != 200:
            self.logger.exit(
                "Crawler: error trying to retrieve this page: %s (%s)\n    From: %s"
                % (filename, chapter_title, url)
            )

        root = None
        try:
            root = html.fromstring(response.text, base_url=urls.SAFARI_BASE_URL)

        except (html.etree.ParseError, html.etree.ParserError) as parsing_error:
            self.logger.error(parsing_error)
            self.logger.exit(
                "Crawler: error trying to parse this page: %s (%s)\n    From: %s"
                % (filename, chapter_title, url)
            )

        return root

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
            self.logger.book_ad_info = 1
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
        self, book_chapters: list[html.HtmlElement], book_path: str, base_url: str
    ) -> None:
        book_cover = None

        for i, chapter in enumerate(book_chapters):
            chapter_title = chapter["title"]
            chapter_filename = chapter["filename"]

            asset_base_url = chapter["asset_base_url"]
            api_v2_detected = False
            if "v2" in chapter["content"]:
                asset_base_url = (
                    urls.SAFARI_BASE_URL
                    + "/api/v2/epubs/urn:orm:book:{}/files".format(self.book_id)
                )
                api_v2_detected = True

            for img_url in chapter.get("images"):
                if api_v2_detected:
                    self.images.append(asset_base_url + "/" + img_url)
                else:
                    self.images.append(urljoin(chapter["asset_base_url"], img_url))

            self.chapter_stylesheets = [x["url"] for x in chapter.get("stylesheets")]
            self.chapter_stylesheets.extend(chapter.get("site_styles"))

            if os.path.isfile(
                os.path.join(
                    book_path, "OEBPS", chapter_filename.replace(".html", ".xhtml")
                )
            ):
                if not self.logger.book_ad_info and chapter not in book_chapters[:i]:
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
                    self.logger.book_ad_info = 2
            else:
                first_page = i == 0
                parsed_html = self.oreilly.parse_html(
                    self.get_html(chapter["content"], chapter_filename, chapter_title),
                    first_page,
                    chapter_filename,
                    chapter_title,
                    self.chapter_stylesheets,
                    self.css,
                    base_url,
                    self.book_id,
                )

                self.save_page_html(
                    book_path=book_path,
                    filename=chapter_filename,
                    css=parsed_html.page_css,
                    xhtml=parsed_html.xhtml,
                )

            self.logger.state(len(book_chapters), i + 1)

        return book_cover

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
            response = self.requests_provider(url)
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
            response = self.requests_provider(
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
        if self.logger.book_ad_info == 2:
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
        response = self.requests_provider(urljoin(self.api_url, "toc/"))
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

        navmap, children, depth = self.parse_toc(toc)
        return TableOfContents(navmap, children, depth)

    @staticmethod
    def parse_toc(lst, children=0, depth=0) -> tuple[str, int, int]:
        navmap = ""
        for cc in lst:
            children += 1
            if int(cc["depth"]) > depth:
                depth = int(cc["depth"])

            navmap += (
                '<navPoint id="{0}" playOrder="{1}">'
                "<navLabel><text>{2}</text></navLabel>"
                '<content src="{3}"/>'.format(
                    cc["fragment"] if len(cc["fragment"]) else cc["id"],
                    children,
                    escape(cc["label"]),
                    cc["href"].replace(".html", ".xhtml").split("/")[-1],
                )
            )

            if cc["children"]:
                sr, children, depth = Downloader.parse_toc(
                    cc["children"], children, depth
                )
                navmap += sr

            navmap += "</navPoint>\n"

        return navmap, children, depth


class WinQueue(
    list
):  # TODO: error while use `process` in Windows: can't pickle _thread.RLock objects
    def put(self, el):
        self.append(el)

    def qsize(self):
        return self.__len__()
