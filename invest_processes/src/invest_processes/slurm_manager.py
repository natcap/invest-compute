import json
import logging
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from typing import Any, Optional, Tuple

from google.cloud import storage
from pygeoapi.process.manager.base import BaseManager
from pygeoapi.util import (
    JobStatus,
    ProcessExecutionMode,
    RequestedProcessExecutionMode,
    RequestedResponse
)

LOGGER = logging.getLogger(__name__)
BUCKET_NAME = 'invest-compute-workspaces'
STORAGE_CLIENT = storage.Client()
BUCKET = STORAGE_CLIENT.bucket(BUCKET_NAME)


def upload_directory_to_bucket(dir_path):
    """Upload everything in a given directory to the GCP bucket.

    Args:
        dir_path (str): path to the directory to be uploaded
        bucket_name (str): GCP bucket name

    Returns:
        None
    """
    # get the parent directory of dir_path
    parent_dir = os.path.split(os.path.normpath(dir_path))[0]

    for sub_dir, _, file_names in os.walk(dir_path):
        for file_name in file_names:
            # absolute path including the full path to the directory
            abs_path = os.path.join(sub_dir, file_name)

            # relative path starting from the given directory
            rel_path = os.path.relpath(abs_path, start=parent_dir)

            blob = BUCKET.blob(rel_path)
            blob.upload_from_filename(abs_path)
            LOGGER.debug(f'Uploaded {abs_path} to gs://{BUCKET_NAME}/{rel_path}')


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

    def get_job_status(self, job_id):
        """
        Get a job's status.

        :param job_id: job identifier

        :raises JobNotFoundError: if the job_id does not correspond to a
                                  known job
        :returns: `dict` of job result
        """
        status = self.get_sacct_data(job_id, 'State')
        LOGGER.debug(f'Status of slurm job {job_id}: {status}')
        if not status:
            return None

        if status not in {'PENDING', 'RUNNING'}:
            workspace_dir = self.get_job_metadata(job_id)['results_path']
            print(workspace_dir, os.listdir(workspace_dir))
            if not os.path.exists(os.path.join(workspace_dir, 'job_complete_token')):
                LOGGER.debug('Job finished but post processing not yet complete.')
                return JobStatus.running

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

        # return as if successful in case of failure so that error details
        # can be returned. The user will need to check the logs to confirm
        # whether the model actually succeeded or not.
        # https://github.com/geopython/pygeoapi/issues/2203
        if status_map[status] == JobStatus.failed:
            return JobStatus.successful
        return status_map[status]

    def get_scontrol_data(self, job_id, field_name):
        """Get a slurm job data field value using the scontrol command.

        Args:
            job_id: id of the job to query
            field_name: name of the data field to query

        Returns:
            string field value
        """
        scontrol_command = ['scontrol', '--json', 'show', 'job', str(job_id)]
        LOGGER.debug('Calling scontrol: ' + ' '.join(scontrol_command))
        result = json.loads(subprocess.run(
            scontrol_command, capture_output=True, text=True, check=True
        ).stdout.strip())
        if len(result['jobs']) == 0:
            return None
        return result['jobs'][0][field_name]

    def get_sacct_data(self, job_id, field_name):
        """Get a slurm job data field value using the sacct command.

        Args:
            job_id: id of the job to query
            field_name: name of the data field to query

        Returns:
            string field value
        """
        sacct_command = [
            'sacct', '--noheader', '-X',
            '-j', job_id,
            '-o', field_name]
        LOGGER.debug('Calling sacct: ' + ' '.join(sacct_command))
        result = subprocess.run(
            sacct_command, capture_output=True, text=True, check=True
        ).stdout.strip()
        LOGGER.debug(f'stdout from sacct command: {result}')
        return result

    def get_job_metadata(self, job_id):
        """
        Get a job's metadata as stored in the slurm job comment.

        Unlike other job data, the 'comment' field doesn't seem to be added to
        the database until the job finishes. So we first try `scontrol`, which
        can only return data for jobs that are running, and if that fails we try
        `sacct`, which has the data for jobs that have finished.

        :param job_id: job identifier

        :raises JobNotFoundError: if the job_id does not correspond to a
                                  known job
        :returns: `dict` of job result
        """
        comment = json.loads(self.get_scontrol_data(job_id, 'comment'))
        if not comment:
            # increase returned field width up to 1000 characters
            comment = json.loads(self.get_sacct_data(job_id, 'Comment%1000'))
        if not comment:
            raise ValueError('job comment not found by scontrol or sacct')
        return comment

    def get_job_submit_time(self, job_id):
        return self.get_sacct_data(job_id, 'Submit')

    def get_job_start_time(self, job_id):
        return self.get_sacct_data(job_id, 'Start')

    def get_job_end_time(self, job_id):
        return self.get_sacct_data(job_id, 'End')

    def get_job(self, job_id: str) -> dict:
        """
        Get a job status. Called by the /jobs/<job_id> endpoint.

        :param job_id: job identifier

        :raises JobNotFoundError: if the job_id does not correspond to a
                                  known job
        :returns: `dict` of job result
        """
        job_metadata = self.get_job_metadata(job_id)
        return {
            "type": "process",
            "identifier": job_id,
            "process_id": job_metadata['process_id'],
            "location": job_metadata['results_path'],
            "created": self.get_job_submit_time(job_id),
            "started": self.get_job_start_time(job_id),
            "finished": self.get_job_end_time(job_id),
            "updated": self.get_job_submit_time(job_id),
            "status": self.get_job_status(job_id).value,
            "mimetype": "application/json",
            "message": "",
            "progress": -1
        }

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
        job_info = self.get_job(job_id)
        if job_info['status'] != JobStatus.successful.value:
            return (None,)
        with open(job_info["location"], "r") as file:
            data = json.load(file)
        return job_info["mimetype"], data

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

    def monitor_job_status(self, job_id, workspace_dir, process_output_func):
        """Poll the slurm job until it completes, then perform final processing.

        Args:
            job_id: id of the slurm job
            workspace_dir: slurm job's workspace directory
            process_output_func: the Process's output processing method that will
                be run after the job completes

        Returns:
            None
        """
        try:
            # wait for the slurm job to complete
            while True:
                print('monitoring', os.listdir(workspace_dir))
                # check the 'state' string from the job data in sacct
                status = self.get_job_status(job_id)
                LOGGER.debug(f'Status of slurm job {job_id}: {status}')
                if status in {JobStatus.successful, JobStatus.failed, JobStatus.dismissed}:
                    break

            # get the exit code from the job data in sacct
            # is returned in the format <exit code>:<signal number>
            exit_code = int(self.get_sacct_data(job_id, 'ExitCode').split(':')[0])
            LOGGER.debug(f'Exit code of slurm job {job_id}: {exit_code}')
            if exit_code != 0:
                LOGGER.error(f'Job {job_id} finished with non-zero exit code: {exit_code}')

            print('process output func', os.listdir(workspace_dir))
            # process outputs, should update results.json in the workspace
            process_output_func(workspace_dir)

        except Exception as err:
            # TODO assess correct exception type and description to help users
            # NOTE, the /results endpoint should return the error HTTP status
            # for jobs that failed, the specification says that failing jobs
            # must still be able to be retrieved with their error message
            # intact, and the correct HTTP error status at the /results
            # endpoint, even if the /result endpoint correctly returns the
            # failure information (i.e. what one might assume is a 200
            # response).
            outputs = {
                'type': 'process',
                'code': 'InvalidParameterValue',
                'description': f'Error executing process: {err}',
                'workspace': workspace_dir
            }
            LOGGER.exception(err)

        finally:
            try:
                # Upload the workspace even if something went wrong, so that the
                # user can access the slurm related files and any partial results.
                LOGGER.debug(f'Copying workspace for job {job_id} to bucket')
                upload_directory_to_bucket(workspace_dir)
            finally:
                # write token to workspace directory
                # this marks that post processing is complete
                with open(os.path.join(workspace_dir, 'job_complete_token'), 'w') as file:
                    file.write('job complete')

    def _execute_handler_sync(self, processor, data_dict, requested_outputs=None,
                              subscriber=None, requested_response=RequestedResponse.raw.value):
        """
        Synchronous execution handler

        If the manager has defined `output_dir`, then the result
        will be written to disk
        output store. There is no clean-up of old process outputs.

        Args:
            processor: `pygeoapi.process` object
            data_dict: `dict` of data parameters
            requested_outputs: `dict` optionally specifying the subset of
                required outputs - defaults to all outputs.The value of any
                key may be an object and include the property `transmissionMode`
                (defaults to `value`) Note: 'optional' is for backward
                compatibility.
            requested_response: `RequestedResponse` optionally specifying
                raw or document (default is `raw`)

        Returns:
            tuple of job id, MIME type, response payload, and status
        """
        try:
            job_id, workspace_dir = self.submit_slurm_job(processor, data_dict)
        except Exception as ex:
            LOGGER.error(
                'Something went wrong while trying to submit the slurm job. '
                'We do not have a job id or workspace yet, so there is nothing to '
                'return to the user.')
            raise ex

        # Monitor job in a separate thread until it completes
        monitor_thread = threading.Thread(
            target=self.monitor_job_status,
            args=(job_id, workspace_dir, processor.process_output))
        monitor_thread.start()
        monitor_thread.join()
        final_status = self.get_job_status(job_id)

        with open(os.path.join(workspace_dir, 'results.json')) as results_file:
            outputs = json.load(results_file)

        if requested_response == RequestedResponse.document.value:
            outputs = {
                'outputs': [outputs]
            }
        return job_id, 'application/json', outputs, final_status

    def _execute_handler_async(self, processor, data_dict, requested_outputs=None,
                               requested_response=RequestedResponse.raw.value):
        """
        Asynchronous execution handler

        Args:
            processor: `pygeoapi.process` object
            data_dict: `dict` of data parameters
            requested_outputs: `dict` optionally specifying the subset of
                required outputs - defaults to all outputs.The value of any
                key may be an object and include the property `transmissionMode`
                (defaults to `value`) Note: 'optional' is for backward
                compatibility.
            requested_response: `RequestedResponse` optionally specifying
                raw or document (default is `raw`)

        Returns:
            tuple of job id, MIME type, response payload, and status
        """
        try:
            job_id, workspace_dir = self.submit_slurm_job(processor, data_dict)
        except Exception as ex:
            LOGGER.error(
                'Something went wrong while trying to submit the slurm job. '
                'We do not have a job id or workspace yet, so there is nothing to '
                'return to the user.')
            raise ex

        # Monitor job in a separate thread, don't wait for it to complete
        monitor_thread = threading.Thread(
            target=self.monitor_job_status,
            args=(job_id, workspace_dir, processor.process_output))
        monitor_thread.start()

        outputs = {
            'job_id': job_id,
            'status': JobStatus.accepted.value,
            'type': 'process'
        }
        if requested_response == RequestedResponse.document.value:
            outputs = {
                'outputs': [outputs]
            }

        # wait for the job to be recorded by slurm
        for i in range(60):
            if self.get_job_status(job_id) is not None:
                break
            time.sleep(1)
        else:
            LOGGER.error(
                'Newly submitted job status failed to appear after 60 seconds')

        return job_id, 'application/json', outputs, JobStatus.accepted

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
        workspace_dir = tempfile.mkdtemp(dir=workspace_root, prefix='slurm_wksp_')
        # create the slurm script in the workspace so that the user can see it
        script_path = os.path.join(workspace_dir, 'script.slurm')
        script = processor.create_slurm_script(**data_dict, workspace_dir=workspace_dir)
        with open(script_path, 'w') as fp:
            fp.write(script)

        LOGGER.debug('Content of slurm script to be submitted:\n')
        with open(script_path) as fp:
            LOGGER.debug(fp.read())

        bucket_gs_url = f'gs://{BUCKET_NAME}/{Path(workspace_dir).name}'
        results_json_path = os.path.join(workspace_dir, 'results.json')
        with open(results_json_path, 'w') as fp:
            fp.write(json.dumps({'workspace_url': bucket_gs_url}))

        job_metadata = json.dumps({
            'workdir': workspace_dir,
            'results_path': results_json_path,
            'process_id': processor.metadata['id']
        })

        # Submit the job
        try:
            args = [
                'sbatch', '--parsable',
                '--comment', f'{job_metadata}',  # custom metadata
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
