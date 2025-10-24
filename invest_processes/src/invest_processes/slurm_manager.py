import json
import logging
import os
from typing import Any, Dict, Optional, Tuple
import uuid
import subprocess
import textwrap
import time

from pygeoapi.process.base import BaseProcessor
from pygeoapi.process.manager.base import BaseManager
from pygeoapi.util import (
    get_current_datetime,
    JobStatus,
    ProcessExecutionMode,
    RequestedProcessExecutionMode,
    RequestedResponse,
    Subscriber
)

LOGGER = logging.getLogger(__name__)

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

        all_jobs = pyslurm.db.Jobs().get()
        return all_jobs

    def add_job(self, job_metadata: dict) -> str:
        """
        Add a job

        :param job_metadata: `dict` of job metadata

        :returns: `str` added job identifier
        """
        LOGGER.info('adding job')

        print(job_metadata)

        script = textwrap.dedent("""\
            #!/bin/sh
            #SBATCH --time=1
            echo 'hello from a slurm job' && sleep 10
            """)

        with open('tmp_script.slurm', 'w') as fp:
            fp.write(script)

        with open('tmp_script.slurm') as fp:
            print(fp.read())

        try:
            result = subprocess.run(
                ['sbatch', '--parsable', 'tmp_script.slurm'],
                capture_output=True,
                text=True,
                check=True)
            print(result)
            print(result.stdout)

            LOGGER.info(result.stdout)
        except subprocess.CalledProcessError as e:
            print(e.stdout)
            print(e.stderr)


        # Submit the job
        try:
            job_id = result.stdout.strip()
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
    ) -> Tuple[str, Any, JobStatus, Optional[Dict[str, str]]]:
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

        job_id = str(uuid.uuid1())
        processor = self.get_processor(process_id)
        processor.set_job_id(job_id)
        extra_execute_handler_parameters = {
            'requested_response': requested_response
        }

        print(data_dict)

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

        # Add Job before returning any response.
        current_status = JobStatus.accepted
        # job_metadata = {
        #     'type': 'process',
        #     'identifier': job_id,
        #     'process_id': process_id,
        #     'created': get_current_datetime(),
        #     'started': get_current_datetime(),
        #     'updated': get_current_datetime(),
        #     'finished': None,
        #     'status': current_status.value,
        #     'location': None,
        #     'mimetype': 'application/octet-stream',
        #     'message': 'Job accepted and ready for execution',
        #     'progress': 5
        # }
        # self.add_job(job_metadata)

        # only pass subscriber if supported, otherwise this breaks
        # existing managers
        if self.supports_subscribing:
            extra_execute_handler_parameters['subscriber'] = subscriber

        # TODO: handler's response could also be allowed to include more HTTP
        # headers
        mime_type, outputs, status = handler(
            processor,
            job_id,
            data_dict,
            requested_outputs,
            **extra_execute_handler_parameters)

        return job_id, mime_type, outputs, status, response_headers


    def submit_slurm_job(self, processor, data_dict):
        print(data_dict)

        # Create a workspace directory
        workspace_root = os.path.abspath('workspaces')
        workspace_dir = os.path.join(workspace_root, f'slurm_wksp_{time.time()}')
        # create the slurm script in the workspace so that the user can see it
        script_path = os.path.join(workspace_dir, 'script.slurm')

        processor.create_slurm_script(data_dict, workspace_dir, script_path)
        with open(script_path) as fp:
            print(fp.read())

        # Submit the job
        try:
            result = subprocess.run([
                'sbatch', '--parsable',
                '--chdir', workspace_dir,
                '--output', 'stdout.log',
                '--error', 'stderr.log',
                script_path],
                capture_output=True,
                text=True,
                check=True)
            print(result)
            print(result.stdout)

            LOGGER.info(result.stdout)
        except subprocess.CalledProcessError as e:
            print(e.stdout)
            print(e.stderr)
            raise RuntimeError('Error when submitting slurm job')

        job_id = result.stdout.strip()
        LOGGER.info(f"Job submitted successfully with ID: {job_id}")

        return job_id, workspace_dir


    def _execute_handler_sync(self, p: BaseProcessor, job_id: str,
                              data_dict: dict,
                              requested_outputs: Optional[dict] = None,
                              subscriber: Optional[Subscriber] = None,
                              requested_response: Optional[RequestedResponse] = RequestedResponse.raw.value  # noqa
                              ) -> Tuple[str, Any, JobStatus]:
        """
        Synchronous execution handler

        If the manager has defined `output_dir`, then the result
        will be written to disk
        output store. There is no clean-up of old process outputs.

        :param p: `pygeoapi.process` object
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

        :returns: tuple of MIME type, response payload and status
        """

        extra_execute_parameters = {}

        # only pass requested_outputs if supported,
        # otherwise this breaks existing processes
        if p.supports_outputs:
            extra_execute_parameters['outputs'] = requested_outputs

        self._send_in_progress_notification(subscriber)

        # try:
        if self.output_dir is not None:
            filename = f"{p.metadata['id']}-{job_id}"
            job_filename = self.output_dir / filename
        else:
            job_filename = None

        current_status = JobStatus.running

        job_id, workspace_dir = self.submit_slurm_job(p, data_dict)

        while True:
            # check the 'state' string from the job data in sacct
            status = subprocess.run([
                'sacct', '--noheader', '-X',
                '-j', job_id,
                '-o', 'State'
            ], capture_output=True, text=True, check=True).stdout.strip()
            LOGGER.debug(f'Status of slurm job {job_id}: {status}')

            if status == 'COMPLETED':
                break
            time.sleep(1)

        # get the exit code from the job data in sacct
        exit_code = int(subprocess.run([
            'sacct', '--noheader', '-X', '-j', job_id, '-o', 'ExitCode'
        ], capture_output=True, text=True, check=True).stdout.strip())
        LOGGER.debug(f'Exit code of slurm job {job_id}: {exit_code}')

        workdir = subprocess.run([
            'sacct', '--noheader', '-X', '-j', job_id, '-o', 'WorkDir'
        ], capture_output=True, text=True, check=True).stdout.strip()

        if exit_code != 0:
            LOGGER.error(f'Job {job_id} finished with non-zero exit code: {exit_code}')

        outputs = p.process_output(os.path.join(workspace_dir, f'{job_id}_stdout.log'))
        outputs['workspace'] = workdir
        print(outputs)

        # copy slurm job workspace to public bucket
        LOGGER.debug(f'Copying workspace for job {job_id} to bucket')


        if requested_response == RequestedResponse.document.value:
            outputs = {
                'outputs': [outputs]
            }

        if self.output_dir is not None:
            LOGGER.debug(f'writing output to {job_filename}')
            if isinstance(outputs, (dict, list)):
                mode = 'w'
                data = json.dumps(outputs, sort_keys=True, indent=4)
                encoding = 'utf-8'
            elif isinstance(outputs, bytes):
                mode = 'wb'
                data = outputs
                encoding = None
            with job_filename.open(mode=mode, encoding=encoding) as fh:
                fh.write(data)

        current_status = JobStatus.successful

        self._send_success_notification(subscriber, outputs=outputs)

        # except Exception as err:
        #     # TODO assess correct exception type and description to help users
        #     # NOTE, the /results endpoint should return the error HTTP status
        #     # for jobs that failed, the specification says that failing jobs
        #     # must still be able to be retrieved with their error message
        #     # intact, and the correct HTTP error status at the /results
        #     # endpoint, even if the /result endpoint correctly returns the
        #     # failure information (i.e. what one might assume is a 200
        #     # response).

        #     current_status = JobStatus.failed
        #     code = 'InvalidParameterValue'
        #     outputs = {
        #         'type': code,
        #         'code': code,
        #         'description': f'Error executing process: {err}'
        #     }
        #     LOGGER.exception(err)
        #     job_metadata = {
        #         'finished': get_current_datetime(),
        #         'updated': get_current_datetime(),
        #         'status': current_status.value,
        #         'location': None,
        #         'mimetype': 'application/octet-stream',
        #         'message': f'{code}: {outputs["description"]}'
        #     }

        #     jfmt = 'application/json'

        #     self._send_failed_notification(subscriber)

        return 'application/json', outputs, current_status


    def __repr__(self):
        return f'<SlurmManager> {self.name}'
