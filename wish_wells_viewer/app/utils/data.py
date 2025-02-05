from typing import Optional
from dataclasses import dataclass, field
from dataclasses_json import dataclass_json

from enum import Enum

@dataclass_json
@dataclass
class DataInformation:
    identifier: str
    path: str
    name: str
    data_type: int
    children: list["DataInformation"] = field(default_factory=lambda: [])


@dataclass_json
@dataclass
class ColoringArrayInformation:
    field: Optional[str]
    array_name: str
    

class DataType(Enum):
    UNKNOWN = 0
    COLLECTION = 1
    REPRESENTATION = 2
    SUBREPRESENTATION = 3
    PROPERTIES = 4
    WELLBORE = 5
    WELLBORE_TRAJECTORY = 6
    WELLBORE_FRAME = 7
    WELLBORE_CHANNEL = 8
    WELLBORE_MARKER_FRAME = 9
    WELLBORE_MARKER = 10
    WELLBORE_COMPLETION = 11
    TIME_SERIES = 12
    PERFORATION = 13
