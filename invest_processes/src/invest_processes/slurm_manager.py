import json
import logging
from multiprocessing import dummy
import os
import subprocess
import tempfile
import textwrap
import time
from typing import Any, Dict, Optional, Tuple
import uuid

from google.cloud import storage
from pygeoapi.process.base import BaseProcessor
from pygeoapi.process.manager.base import BaseManager
from pygeoapi.util import (
    get_current_datetime,
    JobStatus,
    ProcessExecutionMode,
    RequestedProcessExecutionMode,
    RequestedResponse
)

LOGGER = logging.getLogger(__name__)
BUCKET_NAME = 'invest-compute-workspaces'


def upload_directory_to_bucket(dir_path, bucket_name):
    """Upload everything in a given directory to a GCP bucket.

    Args:
        dir_path (str): path to the directory to be uploaded
        bucket_name (str): GCP bucket name

    Returns:
        None
    """
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)

    # get the parent directory of dir_path
    parent_dir = os.path.split(os.path.normpath(dir_path))[0]

    for sub_dir, _, file_names in os.walk(dir_path):
        for file_name in file_names:
            # absolute path including the full path to the directory
            abs_path = os.path.join(sub_dir, file_name)

            # relative path starting from the given directory
            rel_path = os.path.relpath(abs_path, start=parent_dir)

            blob = bucket.blob(rel_path)
            blob.upload_from_filename(abs_path)
            LOGGER.debug(f'Uploaded {abs_path} to gs://{bucket_name}/{rel_path}')


class SlurmManager(BaseManager):
    """Manager that uses slurm"""

    def __init__(self, manager_def: dict):
        """
        Initialize object

        :param manager_def: manager definition

        :returns: `pygeoapi.process.manager.base.BaseManager`
        """
        super().__init__(manager_def)
        self.is_async = True

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
        raise NotImplementedError()

    def add_job(self, job_metadata: dict) -> str:
        """
        Add a job

        :param job_metadata: `dict` of job metadata

        :returns: `str` added job identifier
        """
        raise NotImplementedError()

    def update_job(self, job_id: str, update_dict: dict) -> bool:
        """
        Update a job

        :param job_id: job identifier
        :param update_dict: `dict` of property updates

        :returns: `bool` of status result
        """

        raise NotImplementedError()

    def get_job(self, job_id: str) -> dict:
        """
        Get a job status. Called by the /jobs/<job_id> endpoint.

        :param job_id: job identifier

        :raises JobNotFoundError: if the job_id does not correspond to a
                                  known job
        :returns: `dict` of job result
        """
        status = subprocess.run([
            'sacct', '--noheader', '-X',
            '-j', job_id,
            '-o', 'State'
        ], capture_output=True, text=True, check=True).stdout.strip()
        LOGGER.debug(f'Status of slurm job {job_id}: {status}')

        # Map slurm job statuses to OGC Process job statuses
        # According to the Processes standard, job statuses may be
        # 'accepted', 'running', 'successful', 'failed', or 'dismissed'.
        # Slurm statuses are as defined here: https://slurm.schedmd.com/job_state_codes.html
        status_map = {
            'BOOT_FAIL': JobStatus.failed,      # terminated due to node boot failure
            'CANCELLED': JobStatus.dismissed,   # cancelled by user or administrator
            'COMPLETED': JobStatus.successful,  # completed execution successfully; finished with an exit code of zero on all nodes
            'DEADLINE': JobStatus.failed,       # terminated due to reaching the latest start time that allows the job to reach its deadline given its TimeLimit
            'FAILED': JobStatus.failed,         # completed execution unsuccessfully; non-zero exit code or other failure condition
            'NODE_FAIL': JobStatus.failed,      # terminated due to node failure
            'OUT_OF_MEMORY': JobStatus.failed,  # experienced out of memory error
            'PENDING': JobStatus.accepted,      # queued and waiting for initiation; will typically have a reason code specifying why it has not yet started
            'PREEMPTED': JobStatus.dismissed,   # terminated due to preemption; may transition to another state based on the configured PreemptMode and job characteristics
            'RUNNING': JobStatus.running,       # allocated resources and executing
            'SUSPENDED': JobStatus.dismissed,   # allocated resources but execution suspended, such as from preemption or a direct request from an authorized user
            'TIMEOUT': JobStatus.failed         # terminated due to reaching the time limit, such as those configured in slurm.conf or specified for the individual job
        }

        return status_map[status]


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
        raise NotImplementedError()


    def delete_job(self, job_id: str) -> bool:
        """
        Deletes a job and associated results/outputs

        :param job_id: job identifier

        :raises JobNotFoundError: if the job_id does not correspond to a
                                   known job
        :returns: `bool` of status result
        """
        raise NotImplementedError()

    def execute_process(
            self, process_id, data_dict, execution_mode=None,
            requested_outputs=None, subscriber=None,
            requested_response=RequestedResponse.raw.value):
        """
        Default process execution handler

        :param process_id: process identifier
        :param data_dict: `dict` of data parameters
        :param execution_mode: `str` optionally specifying sync or async
                               processing.
        :param requested_outputs: `dict` optionally specifying the subset of
                                  required outputs - defaults to all outputs.
                                  The value of any key may be an object and
                                  include the property `transmissionMode`
                                  (default is `value`)
                                  Note: 'optional' is for backward
                                  compatibility.
        :param subscriber: `Subscriber` optionally specifying callback urls
        :param requested_response: `RequestedResponse` optionally specifying
                                   raw or document (default is `raw`)


        :raises UnknownProcessError: if the input process_id does not
                                     correspond to a known process
        :returns: tuple of job_id, MIME type, response payload, status and
                  optionally additional HTTP headers to include in the final
                  response
        """
        processor = self.get_processor(process_id)

        if execution_mode == RequestedProcessExecutionMode.respond_async:
            job_control_options = processor.metadata.get(
                'jobControlOptions', [])
            # client wants async - do we support it?
            process_supports_async = (
                ProcessExecutionMode.async_execute.value in job_control_options
                )
            if self.is_async and process_supports_async:
                LOGGER.debug('Asynchronous execution')
                handler = self._execute_handler_async
                response_headers = {
                    'Preference-Applied': (
                        RequestedProcessExecutionMode.respond_async.value)
                }
            else:
                LOGGER.debug('Synchronous execution')
                handler = self._execute_handler_sync
                response_headers = {
                    'Preference-Applied': (
                        RequestedProcessExecutionMode.wait.value)
                }
        elif execution_mode == RequestedProcessExecutionMode.wait:
            # client wants sync - pygeoapi implicitly supports sync mode
            LOGGER.debug('Synchronous execution')
            handler = self._execute_handler_sync
            response_headers = {
                'Preference-Applied': RequestedProcessExecutionMode.wait.value}
        else:  # client has no preference
            # according to OAPI - Processes spec we ought to respond with sync
            LOGGER.debug('Synchronous execution')
            handler = self._execute_handler_sync
            response_headers = None

        job_id, mime_type, outputs, status = handler(
            processor,
            data_dict,
            requested_outputs,
            requested_response=requested_response)

        return job_id, mime_type, outputs, status, response_headers


    def _execute_handler_sync(self, processor, data_dict, requested_outputs=None,
                               subscriber=None, requested_response=RequestedResponse.raw.value):
        """
        Synchronous execution handler

        If the manager has defined `output_dir`, then the result
        will be written to disk
        output store. There is no clean-up of old process outputs.

        :param processor: `pygeoapi.process` object
        :param data_dict: `dict` of data parameters
        :param requested_outputs: `dict` optionally specifying the subset of
                                  required outputs - defaults to all outputs.
                                  The value of any key may be an object and
                                  include the property `transmissionMode`
                                  (defaults to `value`)
                                  Note: 'optional' is for backward
                                  compatibility.
        :param requested_response: `RequestedResponse` optionally specifying
                                   raw or document (default is `raw`)

        :returns: tuple of MIME type, response payload and status
        """
        job_id, mimetype, outputs, status = self._execute_handler_async(
            processor, data_dict, requested_outputs, requested_response)

        try:
            # wait for the slurm job to complete
            while True:
                # check the 'state' string from the job data in sacct
                status = self.get_job(job_id)
                LOGGER.debug(f'Status of slurm job {job_id}: {status}')

                # TODO: make this more resilient to other possible job states
                if status == 'COMPLETED' or status == 'FAILED':
                    break
                time.sleep(1)

            # get the exit code from the job data in sacct
            exit_code = int(subprocess.run([
                'sacct', '--noheader', '-X', '-j', job_id, '-o', 'ExitCode'
            ], capture_output=True, text=True, check=True).stdout.strip().split(':')[0])
            LOGGER.debug(f'Exit code of slurm job {job_id}: {exit_code}')

            if exit_code != 0:
                LOGGER.error(f'Job {job_id} finished with non-zero exit code: {exit_code}')

            outputs = processor.process_output(workspace_dir)
            outputs['workspace'] = workspace_dir

        except Exception as err:
            # TODO assess correct exception type and description to help users
            # NOTE, the /results endpoint should return the error HTTP status
            # for jobs that failed, the specification says that failing jobs
            # must still be able to be retrieved with their error message
            # intact, and the correct HTTP error status at the /results
            # endpoint, even if the /result endpoint correctly returns the
            # failure information (i.e. what one might assume is a 200
            # response).
            current_status = JobStatus.failed
            code = 'InvalidParameterValue'
            outputs = {
                'type': code,
                'code': code,
                'description': f'Error executing process: {err}',
                'workspace': workspace_dir
            }
            LOGGER.exception(err)

        finally:
            # Upload the workspace even if something went wrong, so that the
            # user can access the slurm related files and any partial results.
            LOGGER.debug(f'Copying workspace for job {job_id} to bucket')
            upload_directory_to_bucket(workspace_dir, BUCKET_NAME)


        return 'application/json', None, JobStatus.accepted


    def _execute_handler_async(self, processor, data_dict, requested_outputs=None,
                              requested_response=RequestedResponse.raw.value):
        """
        Asynchronous execution handler

        :param processor: `pygeoapi.process` object
        :param job_id: job identifier
        :param data_dict: `dict` of data parameters
        :param requested_outputs: `dict` optionally specifying the subset of
                                  required outputs - defaults to all outputs.
                                  The value of any key may be an object and
                                  include the property `transmissionMode`
                                  (defaults to `value`)
                                  Note: 'optional' is for backward
                                  compatibility.
        :param subscriber: optional `Subscriber` specifying callback URLs
        :param requested_response: `RequestedResponse` optionally specifying
                                   raw or document (default is `raw`)

        :returns: tuple of None (i.e. initial response payload)
                  and JobStatus.accepted (i.e. initial job status)
        """
        try:
            job_id, workspace_dir = self.submit_slurm_job(processor, data_dict)
        except Exception as ex:
            LOGGER.error(
                'Something went wrong while trying to submit the slurm job. '
                'We do not have a job id or workspace yet, so there is nothing to '
                'return to the user.')
            raise ex

        job_status = self.get_job(job_id)
        outputs = {
            'job_id': job_id,
            'status': job_status,
            'type': 'process'
        }

        if requested_response == RequestedResponse.document.value:
            outputs = {
                'outputs': [outputs]
            }

        return job_id, 'application/json', outputs, job_status


    def submit_slurm_job(self, processor, data_dict):
        """Submit a slurm job to execute the process.

        Args:
            processor (Processor): processor to be executed
            data_dict (dict): user data to pass to the processor

        Returns:
            job_id, workspace_dir
        """
        # Create a workspace directory for the slurm job
        # This will contain the slurm script, stdout and stderr logs,
        # and the process being run may create additional outputs in it.
        # This entire directory will be copied over to GCP for the user to
        # access after the job finishes.
        workspace_root = os.path.abspath('workspaces')
        os.makedirs(workspace_root, exist_ok=True)
        workspace_dir = tempfile.mkdtemp(dir=workspace_root, prefix=f'slurm_wksp_')
        # create the slurm script in the workspace so that the user can see it
        script_path = os.path.join(workspace_dir, 'script.slurm')
        script = processor.create_slurm_script(**data_dict, workspace_dir=workspace_dir)
        with open(script_path, 'w') as fp:
            fp.write(script)

        LOGGER.debug('Content of slurm script to be submitted:\n')
        with open(script_path) as fp:
            LOGGER.debug(fp.read())

        # Submit the job
        try:
            args = [
                'sbatch', '--parsable',
                '--chdir', workspace_dir,
                '--output', 'stdout.log',  # relative to the slurm workspace dir
                '--error', 'stderr.log',
                script_path]
            LOGGER.info(
                f'Submitting slurm job with the following command:\n{args}')
            result = subprocess.run(
                args, capture_output=True, text=True, check=True)
            LOGGER.info(f'stdout from sbatch: {result.stdout}')

        except subprocess.CalledProcessError as e:
            raise RuntimeError('Error when submitting slurm job') from e

        job_id = result.stdout.strip()
        LOGGER.info(f"Job submitted successfully with ID: {job_id}")

        return job_id, workspace_dir


    def __repr__(self):
        return f'<SlurmManager> {self.name}'
