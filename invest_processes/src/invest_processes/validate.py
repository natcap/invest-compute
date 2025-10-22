import importlib
import logging
import os
import tempfile
import textwrap
import time

from natcap.invest import datastack, models, spec, utils
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
    'jobControlOptions': ['async-execute'],
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

    def create_slurm_script(self, data, path):

        # Extract model ID and parameters from the datastack file
        datastack_path = data.get('datastack_path')

        try:
            model_id = datastack.extract_parameter_set(datastack_path).model_id
        except Exception as error:
            raise ProcessorExecuteError(
                1, "Error when parsing JSON datastack:\n    " + str(error))

        # Create a workspace directory
        workspace_root = os.path.abspath('workspaces')
        workspace_dir = os.path.join(workspace_root, f'{model_id}_{time.time()}')

        script = textwrap.dedent(f"""\
            #!/bin/sh
            #SBATCH --time=10
            invest validate --json {datastack_path}
            """)

        with open(path, 'w') as fp:
            fp.write(script)

        outputs = {'workspace_dir': workspace_dir}
        return , outputs

    def process_output(self, output_filepath):
        with open(output_filepath) as output_file:
            output = json.load(output_file)
        return output

    def execute(self, data, outputs=None):
        """Execute the process.

        Args:
            data: dictionary of data inputs
            outputs:

        Returns:
            Tuple of (mimetype, outputs)
        """
        # Extract model ID and parameters from the datastack file
        try:
            parameter_set = datastack.extract_parameter_set(
                data.get('datastack_path'))
        except Exception as error:
            raise ProcessorExecuteError(
                1, 'Error when parsing JSON datastack:\n    ' + str(error))

        # Import the model
        try:
            model_module = models.pyname_to_module[
                models.model_id_to_pyname[parameter_set.model_id]]
        except KeyError as ex:
            raise ValueError(f'model ID {parameter_set.model_id} not found')

        LOGGER.log(
            datastack.ARGS_LOG_LEVEL,
            'Validating parameters: \n' +
            datastack.format_args_dict(
                parameter_set.args,
                parameter_set.model_id))

        try:
            validation_errors = model_module.validate(parameter_set.args)
        except Exception as ex:
            LOGGER.error(
                f'An error occurred during validation: {ex}', exc_info=ex)
            raise ProcessorExecuteError(
                'An error occurred during validation. See the log file in '
                'the workspace for details. \n Workspace: ' + workspace_dir)

        outputs = {'validation_errors': []}
        for (input_ids, error_message) in validation_errors:
            outputs['validation_errors'].append({
                'input_ids': input_ids,
                'error_message': error_message
            })

        return 'application/json', outputs

    def __repr__(self):
        return f'<InVESTValidateProcessor> {self.name}'
