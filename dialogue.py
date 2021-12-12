from dataclasses import dataclass
from typing import Callable, List, Iterable
import asyncio


@dataclass
class Dialogue:

    def __init__(self,
                 valid_choice_callback: Callable,
                 success_message: str = None,
                 invalid_choice_message: str = None,
                 possible_choices: Iterable = None,
                 *args,
                 **kwargs):
        self.choice_callback = valid_choice_callback
        self.success_message = success_message
        self.invalid_choice_message = invalid_choice_message
        self.possible_inputs = possible_choices
        self.callback_args = args
        self.callback_kwargs = kwargs


class YesNoDialogue(Dialogue):

    def __init__(self,
                 yes_callback: Callable,
                 yes_message: str,
                 no_message: str,
                 no_callback: Callable = None):
        super().__init__(
            valid_choice_callback=self._on_choice,
            invalid_choice_message='You can only type y (yes) or n (no)',
            possible_choices=['y', 'Y', 'n', 'N']
        )
        self.yes_message = yes_message
        self.no_message = no_message
        self.yes_callback = yes_callback
        self.no_callback = no_callback

    async def _on_choice(self, channel, choice: str):
        choice = choice.lower()
        if choice == 'y':
            await channel.send(self.yes_message)
            if callable(self.yes_callback):
                self.yes_callback()
        if choice == 'n':
            await channel.send(self.no_message)
            if callable(self.no_callback):
                self.no_callback()
