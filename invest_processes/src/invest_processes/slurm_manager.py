import logging
from typing import Any, Dict, Optional, Tuple
import uuid

from pygeoapi.process.manager.base import BaseManager
from pygeoapi.util import (
    JobStatus,
    RequestedProcessExecutionMode,
    RequestedResponse,
    Subscriber
)
import pyslurm

LOGGER = logging.getLogger(__name__)

class SlurmManager(BaseManager):
    """generic Manager ABC"""

    def __init__(self, manager_def: dict):
        """
        Initialize object

        :param manager_def: manager definition

        :returns: `pygeoapi.process.manager.base.BaseManager`
        """

        super().__init__(manager_def)

    def get_jobs(self,
                 status: JobStatus = None,
                 limit: Optional[int] = None,
                 offset: Optional[int] = None
                 ) -> dict:
        """
        Get process jobs, optionally filtered by status

        :param status: job status (accepted, running, successful,
                       failed, results) (default is all)
        :param limit: number of jobs to return
        :param offset: pagination offset

        :returns: dict of list of jobs (identifier, status, process identifier)
                  and numberMatched
        """

        all_jobs = pyslurm.db.Jobs().get()
        return all_jobs

    def add_job(self, job_metadata: dict) -> str:
        """
        Add a job

        :param job_metadata: `dict` of job metadata

        :returns: `str` added job identifier
        """
        LOGGER.info('adding job')

        # Define job parameters using JobSubmitDescription
        job_desc = pyslurm.JobSubmitDescription(
            name="my_pyslurm_job",  # Name of your job
            time_limit=30,          # Time limit in minutes
            partition="debug",      # Specify the partition/queue
            nodes=1,                # Number of nodes requested
            ntasks=1,               # Number of tasks
            cpus_per_task=2,        # CPUs per task
            script="""#!/bin/bash
        srun hostname
        srun sleep 10
        echo "Job finished"
        """  # The actual shell script to be executed
        )

        # Submit the job
        try:
            job_id = job_desc.submit()
            LOGGER.info(f"Job submitted successfully with ID: {job_id}")
        except pyslurm.SlurmError as e:
            LOGGER.error(f"Error submitting job: {e}")
        return job_id

    def update_job(self, job_id: str, update_dict: dict) -> bool:
        """
        Updates a job

        :param job_id: job identifier
        :param update_dict: `dict` of property updates

        :returns: `bool` of status result
        """

        raise NotImplementedError()

    def get_job(self, job_id: str) -> dict:
        """
        Get a job (!)

        :param job_id: job identifier

        :raises JobNotFoundError: if the job_id does not correspond to a
                                  known job
        :returns: `dict` of job result
        """
        job_info = pyslurm.db.Job.load(job_id, with_script=True)

        if job_info:
            print(f"Job Name: {job_info.job_name}")
            print(f"Job State: {job_info.state}")
            print(f"Batch Script: {job_info.script}")
        else:
            print(f"Job with ID {job_id} not found.")
        return job_info

    def get_job_result(self, job_id: str) -> Tuple[str, Any]:
        """
        Returns the actual output from a completed process

        :param job_id: job identifier

        :raises JobNotFoundError: if the job_id does not correspond to a
                                  known job
        :raises JobResultNotFoundError: if the job-related result cannot
                                         be returned
        :returns: `tuple` of mimetype and raw output
        """

        raise JobResultNotFoundError()

    def delete_job(self, job_id: str) -> bool:
        """
        Deletes a job and associated results/outputs

        :param job_id: job identifier

        :raises JobNotFoundError: if the job_id does not correspond to a
                                   known job
        :returns: `bool` of status result
        """
        step_id = 0     # Replace with the step ID (0 for the main job step)
        job_step = pyslurm.JobStep(job_id, step_id)

        try:
            # Cancel the job step
            job_step.cancel()

            LOGGER.info(f"Successfully cancelled job step {job_id}.{step_id}")
        except pyslurm.RPCError as e:
            LOGGER.error(f"Failed to cancel job step {job_id}.{step_id}: {e}")

    def execute_process(
            self,
            process_id: str,
            data_dict: dict,
            execution_mode: Optional[RequestedProcessExecutionMode] = None,
            requested_outputs: Optional[dict] = None,
            subscriber: Optional[Subscriber] = None,
            requested_response: Optional[RequestedResponse] = RequestedResponse.raw.value  # noqa
    ) -> Tuple[str, str, Any, JobStatus, Optional[Dict[str, str]]]:
        """
        Default process execution handler

        :param process_id: process identifier
        :param data_dict: `dict` of data parameters
        :param execution_mode: requested execution mode
        :param requested_outputs: `dict` optionally specify the subset of
            required outputs - defaults to all outputs.
            The value of any key may be an object and include the property
            `transmissionMode` - defaults to `value`.
            Note: 'optional' is for backward compatibility.
        :param subscriber: `Subscriber` optionally specifying callback urls
        :param requested_response: `RequestedResponse` optionally specifying
                                   raw or document (default is `raw`)

        :raises UnknownProcessError: if the input process_id does not
                                     correspond to a known process
        :returns: tuple of job_id, MIME type, response payload, status and
                  optionally additional HTTP headers to include in the final
                  response
        """

        jfmt = 'application/json'

        response_headers = None
        if execution_mode is not None:
            response_headers = {
                'Preference-Applied': RequestedProcessExecutionMode.wait.value}
            if execution_mode == RequestedProcessExecutionMode.respond_async:
                LOGGER.debug('Dummy manager does not support asynchronous')
                LOGGER.debug('Forcing synchronous execution')

        self._send_in_progress_notification(subscriber)
        processor = self.get_processor(process_id)
        try:
            jfmt, outputs = processor.execute(
                data_dict, outputs=requested_outputs)
            current_status = JobStatus.successful
            self._send_success_notification(subscriber, outputs)
        except Exception as err:
            outputs = {
                'code': 'InvalidParameterValue',
                'description': f'Error executing process: {err}'
            }
            current_status = JobStatus.failed
            LOGGER.exception(err)
            self._send_failed_notification(subscriber)

        if requested_response == RequestedResponse.document.value:
            outputs = {
                'outputs': [outputs]
            }

        job_id = str(uuid.uuid1())
        return job_id, jfmt, outputs, current_status, response_headers

    def __repr__(self):
        return f'<SlurmManager> {self.name}'
