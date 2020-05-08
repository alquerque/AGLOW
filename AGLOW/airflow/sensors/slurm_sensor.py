from __future__ import print_function
from future import standard_library
standard_library.install_aliases()
from builtins import str
from past.builtins import basestring

from datetime import datetime
import logging
from urllib.parse import urlparse
from time import sleep
import re
import sys
import subprocess
import pdb

import airflow
from airflow import hooks, settings
from airflow.exceptions import AirflowException, AirflowSensorTimeout, AirflowSkipException
from airflow.models import BaseOperator, TaskInstance
from airflow.hooks.base_hook import BaseHook
from airflow.hooks.hdfs_hook import HDFSHook
from airflow.utils.state import State
from airflow.operators.sensors import BaseSensorOperator
from airflow.utils.decorators import apply_defaults


class SlurmSensor(BaseSensorOperator):
    """
    An sensor initialized with the glite-wms job ID. It tracks the status of the job and 
    returns only when all the jobs have exited (finished OK or not)

    :param submit_task: The task which submitted the jobs (should return a glite-wms job ID)
    :type submit_task: string
    :param success_threshold: Currently a dummy
    """
    template_fields = ()
    template_ext = ()
    ui_color = '#7c7287'

    @apply_defaults
    def __init__(self, 
            submit_task, 
            success_threshold=0.9, 
            poke_interval=120,
            timeout=60*60*24*4, 
            *args, **kwargs):
        self.submit_task= submit_task
        self.threshold=success_threshold
        self.job_status = 'PENDING'
        super(SlurmSensor, self).__init__(poke_interval=poke_interval,
                timeout=timeout, *args, **kwargs)

    def get_slurm_status(self, job_id):
        logging.info('Poking slurm job: %s', self.jobID)
        g_proc = subprocess.Popen(['sacct',
                                   '-n',
                                   '--format',
                                   'State',
                                   '-j',
                                   self.jobID],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        g_result = g_proc.communicate()
        return g_result[0]


    def poke(self, context):
        """Function called every (by default 2) minutes. It calls glite-wms-job-status
        on the jobID and exits if all the jobs have finished/crashed. 

        """
        self.jobID=context['task_instance'].xcom_pull(task_ids=self.submit_task)
        if self.jobID==None:
            raise RuntimeError("Could not get the jobID from the "+str(self.submit_task)+" task. ")
        self.jobID = self.jobID.split(' ')[-1]
        self.parse_slurm_status(self.get_slurm_status(self.jobID))

        if self.job_status in ['PENDING', 'SUSPENDED']:
            return False
        elif self.job_status is 'CANCELLED':
            logging.warning("Job aborted from commandline")
            return True
        elif 'COMPLETED' in self.job_status:
            success_rate=1
            logging.info("{} of jobs completed ok", success_rate)
            if success_rate < self.threshold:
                logging.warning("Error success rate "+ str(self.success_rate) + " is lower then "+str(self.threshold))
            return True
        else:
            logging.warning('Job execution failed with %s', self.job_status)
            return True

    def parse_slurm_status(self, status_line):
        self.job_status = status_line.strip()
