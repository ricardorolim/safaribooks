import json

import requests

from safaribooks.logger import Logger


class Session:
    def __init__(self, logger: Logger, session: requests.Session):
        self.logger = logger
        self.session = session

    def request(
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

        if self.is_redirect(response) and perform_redirect:
            if not response.next:
                self.logger.error("Redirect expected but no redirect URL found")
                return

            return self.request(response.next.url, is_post, None, perform_redirect)
            # TODO: How about **kwargs?

        return response

    def save(self, cookies_file) -> None:
        json.dump(self.session.cookies.get_dict(), open(cookies_file, "w"))

    def is_redirect(self, response) -> bool:
        return response.status_code in (301, 302, 303, 307, 308) and 'Location' in response.headers

