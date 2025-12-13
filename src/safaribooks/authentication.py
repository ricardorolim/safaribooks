import json
import os
import requests

from safaribooks import urls
from safaribooks.logger import Logger
from safaribooks.safari_session import Session

USE_PROXY = False
PROXIES = {"https": "https://127.0.0.1:8080"}

LOGIN_URL = f"https://www.{urls.ORLY_DOMAIN}/member/login/"
LOGIN_ENTRY_URL = urls.SAFARI_BASE_URL + "/login/unified/?next=/home/"
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": LOGIN_ENTRY_URL,
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
}


class Authenticator:
    def __init__(self, logger: Logger) -> None:
        self.logger = logger

    def login(self, cookies_file: str) -> Session:
        session = requests.Session()

        if USE_PROXY:  # DEBUG
            session.proxies = PROXIES
            session.verify = False

        session.headers.update(HEADERS)

        if not os.path.isfile(cookies_file):
            self.logger.exit(
                "Login: unable to find `cookies.json` file.\n"
                "    Please use the `--cred` or `--login` options to perform the login."
            )

        session.cookies.update(json.load(open(cookies_file)))

        self.safari_session = Session(self.logger, session)

        self.check_login()

        return self.safari_session

    def check_login(self):
        response = self.safari_session.requests_provider(urls.PROFILE_URL, perform_redirect=False)

        if not response:
            self.logger.exit("Login: unable to reach Safari Books Online. Try again...")

        elif response.status_code != 200:
            self.logger.exit("Authentication issue: unable to access profile page.")

        elif 'user_type":"Expired"' in response.text:
            self.logger.exit("Authentication issue: account subscription expired.")

        self.logger.info("Successfully authenticated.", state=True)
