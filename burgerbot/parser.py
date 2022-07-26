import datetime
import time
import logging
from dataclasses import dataclass
from typing import List
from re import S

import requests
from bs4 import BeautifulSoup

ua_url = "https://service.berlin.de/terminvereinbarung/termin/tag.php?termin=1&dienstleister=330857&anliegen[]=330869&herkunft=1"


def build_url(id: int) -> str:
    if id == -2:
        return ua_url
    return f"https://service.berlin.de/terminvereinbarung/termin/tag.php?termin=0&anliegen[]={id}&dienstleisterlist=122210,122217,327316,122219,327312,122227,327314,122231,327346,122243,327348,122252,329742,122260,329745,122262,329748,122254,329751,122271,327278,122273,327274,122277,327276,330436,122280,327294,122282,327290,122284,327292,327539,122291,327270,122285,327266,122286,327264,122296,327268,150230,329760,122301,327282,122297,327286,122294,327284,122312,329763,122314,329775,122304,327330,122311,327334,122309,327332,122281,327352,122279,329772,122276,327324,122274,327326,122267,329766,122246,327318,122251,327320,122257,327322,122208,327298,122226,327300&herkunft=http%3A%2F%2Fservice.berlin.de%2Fdienstleistung%2F120686%2F"


@dataclass
class Slot:
    msg: str
    service_id: int


@dataclass
class Poll:
    time: float
    status: str


class Parser:
    def __init__(self, services: List[int]) -> None:
        self.services = services
        self.last_poll: dict = {}
        self.proxy_on: bool = False
        self.parse()

    def __get_url(self, url) -> requests.Response:
        try:
            if self.proxy_on:
                return requests.get(
                    url, proxies={"https": "socks5://127.0.0.1:9050"}, timeout=10
                )
            return requests.get(url, timeout=10)
        except requests.exceptions.ConnectionError:
            logging.warn("Connection error")
            return None
        except requests.exceptions.ReadTimeout:
            logging.warn("Request timeout")
            return None

    def __toggle_proxy(self) -> None:
        self.proxy_on = not self.proxy_on

    def __parse_page(self, page, service_id) -> List[str]:
        try:
            logging.info(f"parse_page: status_code is {page.status_code}")
            if page.status_code == 428:
                logging.info("Exceeded rate limit. Sleeping for 300s")
                time.sleep(300)
                self.__toggle_proxy()
                return None
            soup = BeautifulSoup(page.content, "html.parser")
            slots = soup.find_all("td", class_="buchbar")
            is_valid = soup.find_all("td", class_="nichtbuchbar")
            if len(is_valid) > 0 and len(slots) == 0:
                self.last_poll[service_id] = Poll(
                    time=time.time(), status="Page is valid, but no slots found..."
                )
                logging.info("Page is valid, but no slots found...")
            if len(is_valid) > 0 and len(slots) > 0:
                self.last_poll[service_id] = Poll(
                    time=time.time(), status=f"Slots found..."
                )
            return [Slot(slot.a["href"], service_id) for slot in slots]
        except Exception as e:  ## sometimes shit happens
            logging.warn(e)
            self.__toggle_proxy()

    def add_service(self, service_id: int) -> None:
        self.services.append(service_id)

    def remove_service(self, service_id: int) -> None:
        try:
            self.services.remove(service_id)
        except ValueError:
            logging.info(f"{service_id} not in parser")

    def get_status(self, service_id: int) -> Poll:
        try:
            return self.last_poll[service_id]
        except KeyError:
            return Poll(time=time.time(), status="No last status")

    def parse(self) -> List[str]:
        slots = []
        logging.info("Services are: " + str(self.services))
        for s in self.services:
            page = self.__get_url(build_url(s))
            if page == None:
                self.last_poll[s] = Poll(time=time.time(), status=f"Connection issue")
                continue
            slots += self.__parse_page(page, s)
        return slots
