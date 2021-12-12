from dataclasses import dataclass
from typing import Callable, List


class Dialogue:
    dialogue_message: str
    success_message: str
    invalid_choice_message: str
    choice_callback: Callable
    possible_inputs: List = None
