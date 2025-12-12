import logging
import os
import sys
import shutil
from multiprocessing import Value
import traceback
from random import random
from typing import Any
from lxml import html
from safaribooks.project_root import project_root
import safaribooks.urls as urls

class Display:
    BASE_FORMAT = logging.Formatter(
        fmt="[%(asctime)s] %(message)s", datefmt="%d/%b/%Y %H:%M:%S"
    )

    SH_DEFAULT = (
        "\033[0m" if "win" not in sys.platform else ""
    )  # TODO: colors for Windows
    SH_YELLOW = "\033[33m" if "win" not in sys.platform else ""
    SH_BG_RED = "\033[41m" if "win" not in sys.platform else ""
    SH_BG_YELLOW = "\033[43m" if "win" not in sys.platform else ""

    def __init__(self, log_file, cookies_file: str):
        self.output_dir = ""
        self.output_dir_set = False
        self.log_file = os.path.join(project_root(), log_file)

        self.cookies_file = cookies_file

        self.logger = logging.getLogger("SafariBooks")
        self.logger.setLevel(logging.INFO)
        logs_handler = logging.FileHandler(filename=self.log_file)
        logs_handler.setFormatter(self.BASE_FORMAT)
        logs_handler.setLevel(logging.INFO)
        self.logger.addHandler(logs_handler)

        self.columns, _ = shutil.get_terminal_size()

        self.logger.info("** Welcome to SafariBooks! **")

        self.book_ad_info = 0
        self.css_ad_info = Value("i", 0)
        self.images_ad_info = Value("i", 0)
        self.last_request: tuple[Any, ...] = (None,)
        self.in_error = False

        self.state_status = Value("i", 0)
        sys.excepthook = self.unhandled_exception

    def set_output_dir(self, output_dir):
        self.info("Output directory:\n    %s" % output_dir)
        self.output_dir = output_dir
        self.output_dir_set = True

    def unregister(self):
        self.logger.handlers[0].close()
        sys.excepthook = sys.__excepthook__

    def log(self, message):
        try:
            self.logger.info(str(message, "utf-8", "replace"))

        except (UnicodeDecodeError, Exception):
            self.logger.info(message)

    def out(self, put):
        pattern = "\r{!s}\r{!s}\n"
        try:
            s = pattern.format(" " * self.columns, str(put, "utf-8", "replace"))

        except TypeError:
            s = pattern.format(" " * self.columns, put)

        sys.stdout.write(s)

    def info(self, message, state=False):
        self.log(message)
        output = (
            self.SH_YELLOW + "[*]" + self.SH_DEFAULT
            if not state
            else self.SH_BG_YELLOW + "[-]" + self.SH_DEFAULT
        ) + " %s" % message
        self.out(output)

    def error(self, error):
        if not self.in_error:
            self.in_error = True

        self.log(error)
        output = self.SH_BG_RED + "[#]" + self.SH_DEFAULT + " %s" % error
        self.out(output)

    def exit(self, error):
        self.error(str(error))

        if self.output_dir_set:
            output = (
                self.SH_YELLOW
                + "[+]"
                + self.SH_DEFAULT
                + " Please delete the output directory '"
                + self.output_dir
                + "'"
                " and restart the program."
            )
            self.out(output)

        output = self.SH_BG_RED + "[!]" + self.SH_DEFAULT + " Aborting..."
        self.out(output)

        self.save_last_request()
        sys.exit(1)

    def unhandled_exception(self, _, o, tb):
        self.log("".join(traceback.format_tb(tb)))
        self.exit("Unhandled Exception: %s (type: %s)" % (o, o.__class__.__name__))

    def save_last_request(self):
        if any(self.last_request):
            self.log(
                "Last request done:\n\tURL: {0}\n\tDATA: {1}\n\tOTHERS: {2}\n\n\t{3}\n{4}\n\n{5}\n".format(
                    *self.last_request
                )
            )

    def intro(self):
        output = (
            self.SH_YELLOW
            + (
                r"""
       ____     ___         _
      / __/__ _/ _/__ _____(_)
     _\ \/ _ `/ _/ _ `/ __/ /
    /___/\_,_/_/ \_,_/_/ /_/
      / _ )___  ___  / /__ ___
     / _  / _ \/ _ \/  '_/(_-<
    /____/\___/\___/_/\_\/___/
"""
                if random() > 0.5
                else r"""
 ██████╗     ██████╗ ██╗  ██╗   ██╗██████╗
██╔═══██╗    ██╔══██╗██║  ╚██╗ ██╔╝╚════██╗
██║   ██║    ██████╔╝██║   ╚████╔╝   ▄███╔╝
██║   ██║    ██╔══██╗██║    ╚██╔╝    ▀▀══╝
╚██████╔╝    ██║  ██║███████╗██║     ██╗
 ╚═════╝     ╚═╝  ╚═╝╚══════╝╚═╝     ╚═╝
"""
            )
            + self.SH_DEFAULT
        )
        output += "\n" + "~" * (self.columns // 2)

        self.out(output)

    def parse_description(self, desc):
        if not desc:
            return "n/d"

        try:
            return html.fromstring(desc).text_content()

        except (html.etree.ParseError, html.etree.ParserError) as e:
            self.log("Error parsing the description: %s" % e)
            return "n/d"

    def book_info(self, info: dict[str, Any]):
        description = self.parse_description(info.get("description", None)).replace(
            "\n", " "
        )
        for t in [
            ("Title", info.get("title", "")),
            (
                "Authors",
                ", ".join(aut.get("name", "") for aut in info.get("authors", [])),
            ),
            ("Identifier", info.get("identifier", "")),
            ("ISBN", info.get("isbn", "")),
            (
                "Publishers",
                ", ".join(pub.get("name", "") for pub in info.get("publishers", [])),
            ),
            ("Rights", info.get("rights", "")),
            (
                "Description",
                description[:500] + "..." if len(description) >= 500 else description,
            ),
            ("Release Date", info.get("issued", "")),
            ("URL", info.get("web_url", "")),
        ]:
            self.info(
                "{0}{1}{2}: {3}".format(self.SH_YELLOW, t[0], self.SH_DEFAULT, t[1]),
                True,
            )

    def state(self, total, current):
        progress = int(current * 100 / total)
        bar = int(progress * (self.columns - 11) / 100)
        if self.state_status.value < progress:
            self.state_status.value = progress
            sys.stdout.write(
                "\r    "
                + self.SH_BG_YELLOW
                + "["
                + ("#" * bar).ljust(self.columns - 11, "-")
                + "]"
                + self.SH_DEFAULT
                + ("%4s" % progress)
                + "%"
                + ("\n" if progress == 100 else "")
            )

    def done(self, epub_file):
        self.info(
            "Done: %s\n\n"
            % epub_file
            + "    If you like it, please * this project on GitHub to make it known:\n"
            "        https://github.com/lorenzodifuccia/safaribooks\n"
            "    e don't forget to renew your Safari Books Online subscription:\n"
            "        "
            + urls.LEARNING_BASE_URL
            + "\n\n"
            + self.SH_BG_RED
            + "[!]"
            + self.SH_DEFAULT
            + " Bye!!"
        )

    def api_error(self, response):
        message = "API: "
        if "detail" in response and "Not found" in response["detail"]:
            message += (
                "book's not present in Safari Books Online.\n"
                "    The book identifier is the digits that you can find in the URL:\n"
                "    `" + urls.LEARNING_BASE_URL + "/library/view/book-name/XXXXXXXXXXXXX/`"
            )

        else:
            os.remove(self.cookies_file)
            message += (
                "Out-of-Session%s.\n" % (" (%s)" % response["detail"])
                if "detail" in response
                else ""
                + Display.SH_YELLOW
                + "[+]"
                + Display.SH_DEFAULT
                + " Use the `--cred` or `--login` options in order to perform the auth login to Safari."
            )

        return message
