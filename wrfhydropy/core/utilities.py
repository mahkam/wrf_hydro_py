import subprocess
import io
import pandas as pd
import warnings
import f90nml
import deepdiff
import xarray as xr
import pathlib

def compare_nc_nccmp(candidate_nc: str,
                     reference_nc: str,
                     nccmp_options: list = ['--data','--metadata','--force','--quiet'],
                     exclude_vars: list = None):

    """Compare two netcdf files using nccmp
    Args:
        candidate_restart: The path for the candidate restart file
        ref_restarts: The path for the reference restart file
        nccmp_options: List of long-form command line options passed to nccmp,
        see http://nccmp.sourceforge.net/ for options
        exclude_vars: A list of strings containing variables names to
        exclude from the comparison
    Returns:
        Either a pandas dataframe if possible or subprocess object
    """
    #Try and set files to strings
    candidate_nc = str(candidate_nc)
    reference_nc = str(reference_nc)

    # Make list to pass to subprocess
    command_list=['nccmp']

    for item in nccmp_options:
        command_list.append(item)

    command_list.append('-S')

    if exclude_vars is not None:
        # Convert exclude_vars list into a comman separated string
        exclude_vars = ','.join(exclude_vars)
        #append
        command_list.append('-x ' + exclude_vars)

    command_list.append(candidate_nc)
    command_list.append(reference_nc)

    #Run the subprocess to call nccmp
    proc = subprocess.run(command_list,
                          stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE)

    #Check return code
    if proc.returncode != 0:
        # Get stoud into stringio object
        output = io.StringIO()
        output.write(proc.stdout.decode('utf-8'))
        output.seek(0)

        # Open stringio object as pandas dataframe
        try:
            nccmp_out = pd.read_table(output,delim_whitespace=True,header=0)
            return nccmp_out
        except:
            warnings.warn('Probleming reading nccmp output to pandas dataframe,'
                 'returning as subprocess object')
            return proc


def compare_ncfiles(candidate_files: list,
                    reference_files: list,
                    nccmp_options: list = ['--data', '--metadata', '--force', '--quiet'],
                    exclude_vars: list = ['ACMELT','ACSNOW','SFCRUNOFF','UDRUNOFF','ACCPRCP',
                                           'ACCECAN','ACCEDIR','ACCETRAN','qstrmvolrt']):
    """Compare lists of netcdf restart files element-wise. Files must have common names
    Args:
        candidate_files: List of candidate restart file paths
        reference_files: List of reference restart file paths
        nccmp_options: List of long-form command line options passed to nccmp,
        see http://nccmp.sourceforge.net/ for options
        exclude_vars: A list of strings containing variables names to
        exclude from the comparison
    Returns:
        A named list of either pandas dataframes if possible or subprocess objects
    """

    ref_dir = reference_files[0].parent
    output_list = []
    for file_candidate in candidate_files:
        file_reference = ref_dir.joinpath(file_candidate.name)
        if file_reference.is_file():
            nccmp_out = compare_nc_nccmp(candidate_nc=file_candidate,
                                         reference_nc=file_reference,
                                         nccmp_options=nccmp_options,
                                         exclude_vars=exclude_vars)
            output_list.append(nccmp_out)
        else:
            warnings.warn(str(file_candidate) + 'not found in ' + str(ref_dir))
    return output_list

###Retaining for backwards compatibility until deprecated
compare_restarts = compare_ncfiles

def diff_namelist(namelist1: str, namelist2: str, **kwargs) -> dict:
    """Diff two fortran namelist files and return a dictionary of differences.

    Args:
        namelist1: String containing path to the first namelist file.
        namelist2: String containing path to the second namelist file.
        **kwargs: Additional arguments passed onto deepdiff.DeepDiff method
    Returns:
        The differences between the two namelists
    """

    # Read namelists into dicts
    namelist1 = f90nml.read(namelist1)
    namelist2 = f90nml.read(namelist2)
    # Diff the namelists
    differences = deepdiff.DeepDiff(namelist1, namelist2, ignore_order=True, **kwargs)
    differences_dict = dict(differences)
    return (differences_dict)


def open_nwmdataset(paths: list,
                    chunks: dict=None) -> xr.Dataset:
    """Open a multi-file wrf-hydro output dataset

    Args:
        paths: List ,iterable, or generator of file paths to wrf-hydro netcdf output files
        chunks: chunks argument passed on to xarray DataFrame.chunk() method
    Returns:
        An xarray dataset of dask arrays chunked by chunk_size along the feature_id
        dimension concatenated along the time and
        reference_time dimensions
    """

    # Create dictionary of forecasts, i.e. reference times
    ds_dict = dict()
    for a_file in paths:
        ds = xr.open_dataset(a_file)
        ref_time = ds['reference_time'].values[0]
        if ref_time in ds_dict:
            # append the new number to the existing array at this slot
            ds_dict[ref_time].append(ds)
        else:
            # create a new array in this slot
            ds_dict[ref_time] = [ds]

    # Concatenate along time axis for each forecast
    forecast_list = list()
    for key in ds_dict.keys():
        forecast_list.append(xr.concat(ds_dict[key],
                                       dim='time',
                                       coords='minimal'))

    # Concatenate along reference_time axis for all forecasts
    nwm_dataset = xr.concat(forecast_list,
                            dim='reference_time',
                            coords='minimal')

    # Break into chunked dask array
    if chunks is not None:
       nwm_dataset = nwm_dataset.chunk(chunks=chunks)

    return nwm_dataset


def __make_relative__(run_object, basepath=None):
    """Make all file paths relative to a given directory, useful for opening file
    attributes in a run object after it has been moved or copied to a new directory or
    system.
    Args:
        basepath: The base path to use for relative paths. Defaults to run directory.
        This rarely needs to be defined.
    Returns:
        self with relative files paths for file-like attributes
    """
    import wrfhydropy
    if basepath is None:
        basepath = run_object.simulation_dir
    for attr in dir(run_object):
        if attr.startswith('__') is False:
            attr_object = getattr(run_object, attr)
            if type(attr_object) == list:
                relative_list = list()
                for item in attr_object:
                    if type(item) is pathlib.PosixPath or type(
                            item) is wrfhydropy.WrfHydroStatic:
                        relative_list.append(item.relative_to(basepath))
                        setattr(run_object, attr, relative_list)
            if type(attr_object) is wrfhydropy.WrfHydroTs:
                relative_list = list()
                for item in attr_object:
                    if type(item) is pathlib.PosixPath or type(
                            item) is wrfhydropy.WrfHydroStatic:
                        relative_list.append(item.relative_to(basepath))
                        relative_list = wrfhydropy.WrfHydroTs(relative_list)
                        setattr(run_object, attr, relative_list)

            elif type(attr_object) is pathlib.PosixPath:
                setattr(run_object, attr, attr_object.relative_to(basepath))

        if attr == 'simulation':
            __make_relative__(run_object.simulation.domain,
                          basepath=run_object.simulation.domain.domain_top_dir)