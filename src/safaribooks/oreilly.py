import pathlib
from html import escape
from random import random
from typing import cast
from urllib.parse import urljoin, urlparse

from lxml import html

from safaribooks.logger import Logger


class ParsedHtml:
    def __init__(self, cover_url: str | None, page_css: str, xhtml: str):
        self.cover_url = cover_url
        self.page_css = page_css
        self.xhtml = xhtml


class OreillyParser:
    def __init__(self, display: Logger, base_url: str, book_id: int):
        self.logger = display
        self.base_url = base_url
        self.book_id = book_id

    def parse_html(
        self,
        root: html.HtmlElement,
        is_first_page: bool,
        html_filename: str,
        chapter_title: str,
        chapter_stylesheets: list[str],
        css_list: list[str],
    ) -> ParsedHtml:
        if root.xpath("//div[@class='controls']/a/text()"):
            if random() > 0.8:
                self.logger.exit(self.logger.api_error(" "))

        book_content: list[html.HtmlElement] = root.xpath("//div[@id='sbo-rt-content']")
        if not book_content:
            self.logger.exit(
                "Parser: book content's corrupted or not present: %s (%s)"
                % (html_filename, chapter_title)
            )

        page_css = ""
        for chapter_css_url in chapter_stylesheets:
            if chapter_css_url not in css_list:
                css_list.append(chapter_css_url)
                self.logger.log("Crawler: found a new CSS at %s" % chapter_css_url)

            page_css += (
                '<link href="Styles/Style{0:0>2}.css" '
                'rel="stylesheet" type="text/css" />\n'.format(
                    css_list.index(chapter_css_url)
                )
            )

        stylesheet_links: list[html.HtmlElement] = root.xpath(
            "//link[@rel='stylesheet']"
        )
        for e in stylesheet_links:
            css_url = (
                urljoin("https:", e.attrib["href"])
                if e.attrib["href"][:2] == "//"
                else urljoin(self.base_url, e.attrib["href"])
            )

            if css_url not in css_list:
                css_list.append(css_url)
                self.logger.log("Crawler: found a new CSS at %s" % css_url)

            page_css += (
                '<link href="Styles/Style{0:0>2}.css" '
                'rel="stylesheet" type="text/css" />\n'.format(css_list.index(css_url))
            )

        stylesheets = cast(list[html.HtmlElement], root.xpath("//style"))
        for css_list in stylesheets:
            if "data-template" in css_list.attrib and css_list.attrib["data-template"]:
                css_list.text = css_list.attrib["data-template"]
                del css_list.attrib["data-template"]

            try:
                e = html.tostring(css_list, method="xml", encoding="unicode")
                page_css += cast(str, e) + "\n"

            except (html.etree.ParseError, html.etree.ParserError) as parsing_error:
                self.logger.error(parsing_error)
                self.logger.exit(
                    "Parser: error trying to parse one CSS found in this page: %s (%s)"
                    % (html_filename, chapter_title)
                )

        # TODO: add all not covered tag for `link_replace` function
        svg_image_tags = root.xpath("//image")
        for img in svg_image_tags:
            image_attr_href = [x for x in img.attrib.keys() if "href" in x]
            if image_attr_href:
                svg_url = img.attrib.get(image_attr_href[0])
                svg_root = img.getparent().getparent()
                new_img = svg_root.makeelement("img")
                new_img.attrib.update({"src": svg_url})
                svg_root.remove(img.getparent())
                svg_root.append(new_img)

        book_content = cast(html.HtmlElement, book_content[0])
        book_content.rewrite_links(lambda link: self.link_replace(link, self.book_id))

        cover_url: str | None = None
        xhtml = None

        try:
            if is_first_page:
                cover_url, page_css, book_content = self.make_cover(
                    page_css, book_content
                )

            xhtml = html.tostring(book_content, method="xml", encoding="unicode")
            xhtml = str(xhtml)

        except (html.etree.ParseError, html.etree.ParserError) as parsing_error:
            self.logger.error(parsing_error)
            self.logger.exit(
                "Parser: error trying to parse HTML of this page: %s (%s)"
                % (html_filename, chapter_title)
            )

        return ParsedHtml(cover_url, page_css, xhtml)

    def make_cover(
        self, page_css: str, book_content: html.HtmlElement
    ) -> tuple[str | None, str, html.HtmlElement]:
        cover_url = None
        cover = self.get_cover(book_content)

        if cover is not None:
            page_css = (
                "<style>"
                "body{display:table;position:absolute;margin:0!important;height:100%;width:100%;}"
                "#Cover{display:table-cell;vertical-align:middle;text-align:center;}"
                "img{height:90vh;margin-left:auto;margin-right:auto;}"
                "</style>"
            )
            cover_html = html.fromstring('<div id="Cover"></div>')
            cover_div = cover_html.xpath("//div")[0]
            cover_img = cover_div.makeelement("img")
            cover_img.attrib.update({"src": cover.attrib["src"]})
            cover_div.append(cover_img)
            book_content = cover_html

            cover_url = cover.attrib["src"]

        return cover_url, page_css, book_content

    @staticmethod
    def url_is_absolute(url) -> bool:
        return bool(urlparse(url).netloc)

    @staticmethod
    def is_image_link(url: str) -> bool:
        return pathlib.Path(url).suffix[1:].lower() in ["jpg", "jpeg", "png", "gif"]

    def link_replace(self, link: str, book_id: int) -> str:
        if link and not link.startswith("mailto"):
            if not self.url_is_absolute(link):
                if any(
                    x in link for x in ["cover", "images", "graphics"]
                ) or self.is_image_link(link):
                    image = link.split("/")[-1]
                    return "Images/" + image

                return link.replace(".html", ".xhtml")

            elif str(book_id) in link:
                return self.link_replace(link.split(str(book_id))[-1], book_id)

        return link

    @staticmethod
    def get_cover(html_root: html.HtmlElement) -> html.HtmlElement | None:
        lowercase_ns = html.etree.FunctionNamespace(None)
        lowercase_ns["lower-case"] = lambda _, n: n[0].lower() if n else ""

        images = html_root.xpath(
            "//img[contains(lower-case(@id), 'cover') or contains(lower-case(@class), 'cover') or"
            "contains(lower-case(@name), 'cover') or contains(lower-case(@src), 'cover') or"
            "contains(lower-case(@alt), 'cover')]"
        )
        if images:
            return images[0]

        divs = html_root.xpath(
            "//div[contains(lower-case(@id), 'cover') or contains(lower-case(@class), 'cover') or"
            "contains(lower-case(@name), 'cover') or contains(lower-case(@src), 'cover')]//img"
        )
        if divs:
            return divs[0]

        a = html_root.xpath(
            "//a[contains(lower-case(@id), 'cover') or contains(lower-case(@class), 'cover') or"
            "contains(lower-case(@name), 'cover') or contains(lower-case(@src), 'cover')]//img"
        )
        if a:
            return a[0]

        return None

    def parse_toc(self, lst, children=0, depth=0) -> tuple[str, int, int]:
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
                sr, children, depth = self.parse_toc(
                    cc["children"], children, depth
                )
                navmap += sr

            navmap += "</navPoint>\n"

        return navmap, children, depth
