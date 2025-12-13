import json
import re

import requests

from safaribooks.logger import Logger

COOKIE_FLOAT_MAX_AGE_PATTERN = re.compile(r"(max-age=\d*\.\d*)", re.IGNORECASE)


class Session:
    def __init__(self, logger: Logger, session: requests.Session):
        self.logger = logger
        self.session = session

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

    def save_cookies(self, cookies_file) -> None:
        json.dump(self.session.cookies.get_dict(), open(cookies_file, "w"))
