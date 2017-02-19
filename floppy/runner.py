import importlib
import os
import threading

from floppy.train_configuration import TrainParamServer

class StopTraining(Exception): pass


#TODO(fukatani): implement all
class Runner(object):
    def __init__(self):
        self.is_running = False
        self.run_process = None

    def run(self):
        self.is_running = True
        #module_file = os.getcwd() + '/' + TrainParamServer()['NetName'] + '.py'
        module_file = TrainParamServer()['NetName']
        module = importlib.import_module(module_file)
        module.main()
        del module

    def kill(self):
        pass
