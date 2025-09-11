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

    def get_jobs(self, status: JobStatus = None, limit=None, offset=None
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

        return {'jobs': [], 'numberMatched': 0}

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
