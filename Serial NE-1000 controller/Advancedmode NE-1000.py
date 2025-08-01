import serial
import time
import threading
import zipfile  
from pathlib import Path  
from collections import defaultdict 
import re
import FreeSimpleGUI as sg

#custommodules
from Custommodules import Unzipper
from Custommodules import Serialfinder
from Custommodules import Pumpcontroller