import time
import os
import json
import threading
import logging
import sys
from dataclasses import dataclass, asdict
from typing import List
from datetime import datetime

from telegram import ParseMode
from telegram.ext import CommandHandler, Updater
from telegram.ext.callbackcontext import CallbackContext
from telegram.update import Update

from parser import Parser, Slot, build_url


CHATS_FILE = "chats.json"
ua_url = "https://service.berlin.de/terminvereinbarung/termin/tag.php?termin=1&dienstleister=330857&anliegen[]=330869&herkunft=1"
register_prefix = "https://service.berlin.de"

service_map = {
    120686: "Anmeldung",
    120680: "Beglaubigungen",
    120701: "Personalausweis beantragen",
    121151: "Reisepass beantragen",
    121921: "Gewerbeanmeldung",
    327537: "Fahrerlaubnis \- Umschreibung einer ausländischen",
    324280: "Niederlassungserlaubnis oder Erlaubnis",
    318998: "Einbürgerung \- Verleihung der deutschen Staatsangehörigkeit beantragen",
    121591: "Führerschein \- Internationalen Führerschein beantragen",
}


@dataclass
class Message:
    message: str
    ts: int  # timestamp of adding msg to cache in seconds


@dataclass
class User:
    chat_id: int
    services: List[int]

    def __init__(self, chat_id, services=[]):
        self.chat_id = chat_id
        self.services = services

    def marshall_user(self) -> str:
        self.services = list(
            set([s for s in self.services if s in list(service_map.keys())])
        )
        return asdict(self)


class Bot:
    def __init__(self) -> None:
        self.updater = Updater(os.environ["TELEGRAM_API_KEY"])
        self.__init_chats()
        self.users = self.__get_chats()
        self.services = self.__get_uq_services()
        self.parser = Parser(self.services)
        self.dispatcher = self.updater.dispatcher
        self.dispatcher.add_handler(CommandHandler("help", self.__help))
        self.dispatcher.add_handler(CommandHandler("start", self.__start))
        self.dispatcher.add_handler(CommandHandler("stop", self.__stop))
        self.dispatcher.add_handler(CommandHandler("add_service", self.__add_service))
        self.dispatcher.add_handler(CommandHandler("my_services", self.__my_services))
        self.dispatcher.add_handler(CommandHandler("last_status", self.__last_status))
        self.dispatcher.add_handler(
            CommandHandler("remove_service", self.__remove_service)
        )
        self.dispatcher.add_handler(CommandHandler("services", self.__services))
        self.cache: List[Message] = []

    def __get_uq_services(self) -> List[int]:
        services = []
        for u in self.users:
            services.extend(u.services)
        services = filter(lambda x: x in service_map.keys(), services)
        return list(set(services))

    def __init_chats(self) -> None:
        if not os.path.exists(CHATS_FILE):
            with open(CHATS_FILE, "w") as f:
                f.write("[]")

    def __get_chats(self) -> List[User]:
        with open(CHATS_FILE, "r") as f:
            users = [User(u["chat_id"], u["services"]) for u in json.load(f)]
            f.close()
            return users

    def __persist_chats(self) -> None:
        with open(CHATS_FILE, "w") as f:
            json.dump([u.marshall_user() for u in self.users], f)
            f.close()

    def __add_chat(self, chat_id: int) -> None:
        if chat_id not in [u.chat_id for u in self.users]:
            self.users.append(User(chat_id))
            self.__persist_chats()

    def __remove_chat(self, chat_id: int) -> None:
        logging.info("removing the chat " + str(chat_id))
        self.users = [u for u in self.users if u.chat_id != chat_id]
        for s in self.services:
            if not self.__check_service_is_needed(s):
                self.parser.remove_service(int(s))
        self.__persist_chats()

    def __services(self, update: Update, _: CallbackContext) -> None:
        services_text = ""
        for k, v in service_map.items():
            services_text += f"{k} \- {v}\n"
        update.message.reply_text(
            "available services:\n" + services_text, parse_mode=ParseMode.MARKDOWN_V2
        )

    def __help(self, update: Update, _: CallbackContext) -> None:
        try:
            update.message.reply_text(
                """
/start \- start the bot
/stop \- stop the bot
/add\_service \<service\_id\> \- add service to your list
/remove\_service \<service\_id\> \- remove service from your list
/services \- list of available services
/my\_services \- list of services being polled for
/last\_status \- displays the status of the last poll
""",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception as e:
            logging.error(e)

    def __start(self, update: Update, _: CallbackContext) -> None:
        self.__add_chat(update.message.chat_id)
        logging.info(f"got new user with id {update.message.chat_id}")
        update.message.reply_text(
            """
Welcome to BurgerBot
For a list of commands \- type /help
To stop \- type /stop
        """,
            parse_mode=ParseMode.MARKDOWN_V2,
        )

    def __stop(self, update: Update, _: CallbackContext) -> None:
        self.__remove_chat(update.message.chat_id)
        update.message.reply_text(
            "thanks for using me", parse_mode=ParseMode.MARKDOWN_V2
        )

    def __add_service(self, update: Update, _: CallbackContext) -> None:
        logging.info(f"adding service {update.message}")
        try:
            service_id = int(update.message.text.split(" ")[1])
            for u in self.users:
                if u.chat_id == update.message.chat_id:
                    u.services.append(int(service_id))
                    self.parser.add_service(int(service_id))
                    self.__persist_chats()
                    break
            update.message.reply_text(
                f"{service_map[int(service_id)]} added",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception as e:
            update.message.reply_text(
                "Failed to add service, have you specified the service id?",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            logging.error(e)

    def __remove_service(self, update: Update, _: CallbackContext) -> None:
        logging.info(f"removing service {update.message}")
        service_id = int(update.message.text.split(" ")[1])
        for u in self.users:
            if u.chat_id == update.message.chat_id:
                try:
                    u.services.remove(int(service_id))
                except ValueError:
                    logging.info(f"{service_id} not in list")
                self.__persist_chats()
                break
        if not self.__check_service_is_needed(service_id):
            self.parser.remove_service(int(service_id))
        update.message.reply_text(
            f"{service_map[int(service_id)]} removed", parse_mode=ParseMode.MARKDOWN_V2
        )

    def __check_service_is_needed(self, service_id: int) -> bool:
        for u in self.users:
            for s in u.services:
                if s == service_id:
                    return True

    def __my_services(self, update: Update, _: CallbackContext) -> None:
        services: List[str] = []
        for u in self.users:
            if u.chat_id == update.message.chat_id:
                for s in u.services:
                    services.append(f"{s} \- {service_map[s]}")
        update.message.reply_text(
            f"currently polling for:\n{chr(10).join(services)}",
            parse_mode=ParseMode.MARKDOWN_V2,
        )

    def __last_status(self, update: Update, _: CallbackContext) -> None:
        status = []
        for u in self.users:
            for s in u.services:
                st = self.parser.get_status(s)
                status.append(
                    f"{s} \- {datetime.fromtimestamp(st.time).strftime('%c')} \- {st.status}"
                )
        update.message.reply_text(
            f"last statuses for your selected services:\n{chr(10).join(status)}",
            parse_mode=ParseMode.MARKDOWN_V2,
        )

    def __poll(self) -> None:
        self.updater.start_polling()

    def __parse(self) -> None:
        while True:
            slots = self.parser.parse()
            for slot in slots:
                self.__send_message(slot)
            time.sleep(30)

    def __send_message(self, slot: Slot) -> None:
        if self.__msg_in_cache(slot.msg):
            logging.info("Notification is cached already. Do not repeat sending")
            return
        self.__add_msg_to_cache(slot.msg)
        md_msg = f"There are slots on {self.__date_from_msg(slot.msg)} available for booking for {service_map[slot.service_id]}, click [here]({build_url(slot.service_id)}) to check it out"
        users = [u for u in self.users if slot.service_id in u.services]
        for u in users:
            logging.info(f"sending msg to {str(u.chat_id)}")
            try:
                self.updater.bot.send_message(
                    chat_id=u.chat_id, text=md_msg, parse_mode=ParseMode.MARKDOWN_V2
                )
            except Exception as e:
                if "bot was blocked by the user" in e.__str__():
                    logging.info("removing since user blocked bot")
                    self.__remove_chat(u.chat_id)
                else:
                    logging.warning(e)
        self.__clear_cache()

    def __msg_in_cache(self, msg: str) -> bool:
        for m in self.cache:
            if m.message == msg:
                return True
        return False

    def __add_msg_to_cache(self, msg: str) -> None:
        self.cache.append(Message(msg, int(time.time())))

    def __clear_cache(self) -> None:
        cur_ts = int(time.time())
        if len(self.cache) > 0:
            logging.info("clearing some messages from cache")
            self.cache = [m for m in self.cache if (cur_ts - m.ts) < 300]

    def __date_from_msg(self, msg: str) -> str:
        msg_arr = msg.split("/")
        ts = (
            int(msg_arr[len(msg_arr) - 2]) + 7200
        )  # adding two hours to match Berlin TZ with UTC
        return datetime.fromtimestamp(ts).strftime("%d %B")

    def start(self) -> None:
        logging.info("starting bot")
        poll_task = threading.Thread(target=self.__poll)
        parse_task = threading.Thread(target=self.__parse)
        parse_task.start()
        poll_task.start()
        parse_task.join()
        poll_task.join()


def main() -> None:
    bot = Bot()
    bot.start()


if __name__ == "__main__":
    log_level = os.getenv("LOG_LEVEL", "INFO")
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)-5.5s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    main()
