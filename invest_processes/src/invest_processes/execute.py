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
            echo 'hello from a slurm job' && sleep 10
            invest run --datastack {datastack_path} --workspace {workspace_dir} {model_id}
            """)

        with open(path, 'w') as fp:
            fp.write(script)

        outputs = {'workspace_dir': workspace_dir}
        return 'application/json', outputs


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

        try:
            parameter_set = datastack.extract_parameter_set(datastack_path)
        except Exception as error:
            raise ProcessorExecuteError(
                1, "Error when parsing JSON datastack:\n    " + str(error))

        # Import the model
        try:
            model_module = models.pyname_to_module[
                models.model_id_to_pyname[parameter_set.model_id]]
        except KeyError as ex:
            raise ValueError(f'model ID {parameter_set.model_id} not found')

        # Create a workspace directory
        workspace_root = os.path.abspath('workspaces')
        workspace_dir = os.path.join(workspace_root, f'{parameter_set.model_id}_{time.time()}')
        parameter_set.args['workspace_dir'] = workspace_dir

        for arg_key, val in parameter_set.args.items():
            try:
                input_spec = model_module.MODEL_SPEC.get_input(arg_key)
            except KeyError:
                continue
            # Uncomment this for next invest release
            # if type(input_spec) in {spec.RasterInput, spec.SingleBandRasterInput,
            #                         spec.VectorInput}:
            #     parameter_set.args[arg_key] = utils._GDALPath.from_uri(
            #         val).to_normalized_path()

        with utils.prepare_workspace(workspace_dir,
                                     model_id=parameter_set.model_id,
                                     logging_level=logging.DEBUG):
            LOGGER.log(
                datastack.ARGS_LOG_LEVEL,
                'Starting model with parameters: \n' +
                datastack.format_args_dict(
                    parameter_set.args,
                    parameter_set.model_id))

            try:
                model_module.execute(parameter_set.args)
            except Exception as ex:
                LOGGER.error(
                    f'An error occurred during execution: {ex}', exc_info=ex)
                raise ProcessorExecuteError(
                    'An error occurred during execution. See the log file in '
                    'the workspace for details. \n Workspace: ' + workspace_dir)

            LOGGER.info('Generating metadata for results')
            try:
                # If there's an exception from creating metadata
                # I don't think we want to indicate a model failure
                spec.generate_metadata_for_outputs(
                    model_module, parameter_set.args)
            except Exception as ex:
                LOGGER.warning(
                    'Something went wrong while generating metadata', exc_info=ex)

        outputs = {'workspace_dir': workspace_dir}
        return 'application/json', outputs

    def __repr__(self):
        return f'<InVESTExecuteProcessor> {self.name}'
