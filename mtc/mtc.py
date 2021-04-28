"""Classes and methods supporting MTC!"""

import logging

from pwiki.wiki import Wiki
from pwiki.wgen import load_px

from fastilybot.core import FastilyBotBase


log = logging.getLogger(__name__)

_MTC = "Wikipedia:MTC!"
_USER = "FSock"


class MTC(FastilyBotBase):

    def __init__(self) -> None:
        super().__init__(wiki := Wiki())

        if not wiki.login(_USER, pw := load_px().get(_USER)) or not self.com.login(_USER, pw):
            raise RuntimeError("Could not login, is your username and password right?")

        self.wiki: Wiki = wiki

        self.blacklist: set[str] = set(self.wiki.links_on_page(f"{_MTC}/Blacklist"))
        self.whitelist: set[str] = set(self.wiki.links_on_page(f"{_MTC}/Whitelist"))

        
