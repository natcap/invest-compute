import importlib
import logging
import os
import tempfile
import textwrap
import time

from invest_processes import utils
from natcap.invest import datastack, models, spec, utils
from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError

LOGGER = logging.getLogger(__name__)

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
        'workspace_url': {
            'title': 'Workspace URL',
            'description': 'URL to the workspace containing all model results',
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

    def create_slurm_script(self, datastack_url, workspace_dir):
        """Create a script to run with sbatch.

        Args:
            datastack_url: URL to the invest datastack (.tgz) to execute
            workspace_dir: path to the directory that the slurm job will run in

        Returns:
            string contents of the script
        """
        extracted_datastack_dir = os.path.join(workspace_dir, 'datastack')
        utils.download_and_extract_datastack(datastack_url, extracted_datastack_dir)

        # Parse the extracted datastack JSON. Datastack archives created in the
        # workbench should have the JSON file named parameters.invest.json.
        json_path = os.path.join(extracted_datastack_dir, 'parameters.invest.json')
        try:
            model_id = datastack.extract_parameter_set(json_path).model_id
        except Exception as error:
            raise ProcessorExecuteError(
                1, f'Error when parsing JSON datastack:\n{str(error)}')

        # Create a workspace directory
        workspace_dir = os.path.join(workspace_dir, f'{model_id}_workspace')

        return textwrap.dedent(f"""\
            #!/bin/sh
            #SBATCH --time=10
            invest run --datastack {json_path} --workspace {workspace_dir} {model_id}
            """)

    def process_output(self, workspace_dir):
        """Return outputs given a workspace from completed slurm job.

        Args:
            workspace_dir (str): path to the slurm job working directory

        Returns:
            empty dict
        """
        pass


    def __repr__(self):
        return f'<InVESTExecuteProcessor> {self.name}'
