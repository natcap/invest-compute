import json
import logging
import os
import textwrap
import time

from invest_processes.utils import download_and_extract_datastack
from natcap.invest import datastack
from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError

LOGGER = logging.getLogger(__name__)

PROCESS_METADATA = {
    'version': '0.1.0',
    'id': 'invest-validate',
    'title': {
        'en': 'InVEST Validate'
    },
    'description': {
        'en': 'A process that validates inputs to an InVEST model.'
    },
    'jobControlOptions': ['async-execute', 'sync-execute'],
    'keywords': ['invest'],
    'inputs': {
        'datastack_path': {
            'title': 'Datastack path',
            'description': 'The path to the datastack JSON file to validate',
            'schema': {
                'type': 'string'
            },
            'minOccurs': 1,
            'maxOccurs': 1
        }
    },
    'outputs': {
        'validation_errors': {
            'title': 'Validation errors',
            'description': (
                "List of validation errors found in the provided data. Each "
                "list item is an object where the 'error_message' property "
                "describes the problem, and the 'input_ids' property lists the "
                "input IDs which have the problem."),
            'schema': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'input_ids': {
                            'type': 'array',
                            'items': { 'type': 'string' }
                        },
                        'error_message': { 'type': 'string' }
                    }
                },
                'contentMediaType': 'application/json'
            }
        }
    },
    'example': {
        'inputs': {
            'datastack_path': '/Users/emily/invest/data/Carbon/carbon_willamette.invs.json',
        }
    }
}

class ValidateProcessor(BaseProcessor):
    """InVEST validate process"""

    def __init__(self, processor_def):
        """
        Initialize object

        Args:
            processor_def: provider definition

        Returns:
            invest_processes.validate.ValidateProcessor
        """

        super().__init__(processor_def, PROCESS_METADATA)

    def create_slurm_script(self, datastack_url, workspace_dir):
        """Create a script to run with sbatch.

        Args:
            datastack_url: url to the user provided invest datastack to execute
            workspace_dir: path to the directory that the slurm job will run in

        Returns:
            string contents of the script
        """
        extracted_datastack_dir = os.path.join(workspace_dir, 'datastack')
        download_and_extract_datastack(datastack_url, extracted_datastack_dir)

        # Parse the extracted datastack JSON. Datastack archives created in the
        # workbench should have the JSON file named parameters.invest.json.
        json_path = os.path.join(extracted_datastack_dir, 'parameters.invest.json')
        try:
            model_id = datastack.extract_parameter_set(json_path).model_id
        except Exception as error:
            raise ProcessorExecuteError(
                1, f'Error when parsing JSON datastack:\n{str(error)}')

        # Create a workspace directory
        workspace_root = os.path.abspath('workspaces')
        workspace_dir = os.path.join(workspace_root, f'{model_id}_{time.time()}')

        return textwrap.dedent(f"""\
            #!/bin/sh
            #SBATCH --time=10
            invest validate --json {json_path}
            """)

    def process_output(self, workspace_dir):
        """Return outputs given a workspace from completed slurm job.

        Args:
            workspace_dir (str): path to the slurm job working directory

        Returns:
            dict of validation results
        """
        stdout_filepath = os.path.join(workspace_dir, 'stdout.log')
        with open(stdout_filepath) as stdout:
            content = stdout.read()
        LOGGER.debug('Processing stdout:\n')
        LOGGER.debug(content)
        json_output = json.loads(content)

        with open(os.path.join(workspace_dir, 'results.json')) as file:
            results = json.load(file)

        # add validation messages to the results json file
        results['validation_results'] = []
        for (input_ids, error_message) in json_output['validation_results']:
            results['validation_results'].append({
                'input_ids': input_ids,
                'error_message': error_message
            })
        with open(os.path.join(workspace_dir, 'results.json'), 'w') as file:
            json.dump(results, file)

    def __repr__(self):
        return f'<InVESTValidateProcessor> {self.name}'
