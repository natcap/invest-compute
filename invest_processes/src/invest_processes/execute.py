import importlib
import os
import tempfile
import time

from natcap.invest import datastack, models
from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError

PROCESS_METADATA = {
    'version': '0.1.0',
    'id': 'invest-execute',
    'title': {
        'en': 'InVEST Execute'
    },
    'description': {
        'en': 'A process that executes an InVEST model.'
    },
    'jobControlOptions': ['async-execute'],
    'keywords': ['invest'],
    'inputs': {
        'datastack_path': {
            'title': 'Datastack path',
            'description': 'The path to the datastack JSON file to execute',
            'schema': {
                'type': 'string'
            },
            'minOccurs': 1,
            'maxOccurs': 1
        }
    },
    'outputs': {
        'workspace_dir': {
            'title': 'Workspace directory',
            'description': 'Path to the workspace directory containing all model results',
            'schema': {
                'type': 'string',
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

class ExecuteProcessor(BaseProcessor):
    """InVEST execute process"""

    def __init__(self, processor_def):
        """
        Initialize object

        Args:
            processor_def: provider definition

        Returns:
            invest_processes.processes.ExecuteProcessor
        """

        super().__init__(processor_def, PROCESS_METADATA)

    def execute(self, data, outputs=None):
        """Execute the process.

        Args:
            data: dictionary of data inputs
            outputs:

        Returns:
            Tuple of (mimetype, outputs)
        """
        # Extract model ID and parameters from the datastack file
        datastack_path = data.get('datastack_path')
        parameter_set = datastack.extract_parameter_set(datastack_path)

        # Import the model
        try:
            invest_module = models.pyname_to_module[
                models.model_id_to_pyname[parameter_set.model_id]]
        except KeyError as ex:
            raise ValueError(f'model ID {parameter_set.model_id} not found')

        # Create a workspace directory
        workspace_root = os.path.abspath('workspaces')
        workspace_dir = os.path.join(workspace_root, f'{parameter_set.model_id}_{time.time()}')
        parameter_set.args['workspace_dir'] = workspace_dir

        # Execute the model
        invest_module.execute(parameter_set.args)

        outputs = {'workspace_dir': workspace_dir}
        return 'application/json', outputs

    def __repr__(self):
        return f'<InVESTExecuteProcessor> {self.name}'
