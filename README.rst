===================
FESPP on TRAME
===================

Trame application to visualize wells.


Installing
----------

Create a python virtual environment
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: console

    python3.X -m venv ./fespp_on_trame_venv
    
with python3.X the same version of python used in Paraview 


Install the application
^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: console

    pip install -e .


Update paths
^^^^^^^^^^^^^^^^^^^^^^^

In fespp_on_trame/constants.py update paths to:
    * FESPP_PLUGIN_PATH: path to fespp paraview plugin .so (path/to/Fespp.so)
    * LOCAL_EPC_FILE_PATH: Path to epc file to display


Run the application
^^^^^^^^^^^^^^^^^^^

.. code-block:: console

    cd fespp-on-trame
    path/to/pvpython fespp_on_trame --server --venv ../fespp_on_trame_venv/

Build & run Docker Image
^^^^^^^^^^^^^^^^^^

.. code-block:: console

    docker build . -f Dockerfile -t ttl_fespp_on_trame:latest
    docker run -it --rm -p 8080:80 ttl_fespp_on_trame:latest


https://raw.githubusercontent.com/naucoin/VTKData/refs/heads/master/Data/cow.vtp

http://localhost:2222/PETREL_IJK/PETREL_OLYMPUS_TRAME.epc
http://localhost:2222/PETREL_IJK/PETREL_OLYMPUS_TRAME.h5

http://localhost:2222/PETREL_IJK/PETREL_OLYMPUS_TRAME_yay.h5

test URI:
http://localhost/index.html?remote_epc_file_location=aHR0cDovL2xvY2FsaG9zdDoyMjIyL1BFVFJFTF9JSksvUEVUUkVMX09MWU1QVVNfVFJBTUUuZXBj&remote_h5_file_location=aHR0cDovL2xvY2FsaG9zdDoyMjIyL1BFVFJFTF9JSksvUEVUUkVMX09MWU1QVVNfVFJBTUUuaDU=

Test URI 2:
http://localhost/index.html?remote_epc_file_location=aHR0cDovL2xvY2FsaG9zdDoyMjIyL1BFVFJFTF9JSksvUEVUUkVMX09MWU1QVVNfVFJBTUUuZXBj&remote_h5_file_location=aHR0cDovL2xvY2FsaG9zdDoyMjIyL1BFVFJFTF9JSksvUEVUUkVMX09MWU1QVVNfVFJBTUVfeWF5Lmg1

test URI https:
http://localhost/index.html?remote_epc_file_location=aHR0cHM6Ly9yYXcuZ2l0aHVidXNlcmNvbnRlbnQuY29tL25hdWNvaW4vVlRLRGF0YS9yZWZzL2hlYWRzL21hc3Rlci9EYXRhL2Nvdy52dHA=&remote_h5_file_location=aHR0cHM6Ly9naXRodWIuY29tL25hdWNvaW4vVlRLRGF0YS9ibG9iL21hc3Rlci9EYXRhL1NhbXBsZVN0cnVjdEdyaWQudnRr


H5:
http://localhost:2222/NO_EXT/66ec1be1b649845cf2a90e24 2

HDF5 filename: PBENOIT_JEANEZMAR_030_rqiDyn.h5

EPC:
http://localhost:2222/NO_EXT/66ec1be1b649845cf2a90e23 2

other EPC:
    http://localhost:2222/NO_EXT/66ec1be1b649845cf2a90e23 2_nocolormap_zip

test URI:
http://localhost/index.html?remote_h5_file_location=aHR0cDovL2xvY2FsaG9zdDoyMjIyL05PX0VYVC82NmVjMWJlMWI2NDk4NDVjZjJhOTBlMjQgMg==&remote_epc_file_location=aHR0cDovL2xvY2FsaG9zdDoyMjIyL05PX0VYVC82NmVjMWJlMWI2NDk4NDVjZjJhOTBlMjMgMg==&h5filename=PBENOIT_JEANEZMAR_030_rqiDyn.h5
http://localhost/index.html?remote_h5_file_location=aHR0cDovL2xvY2FsaG9zdDoyMjIyL05PX0VYVC82NmVjMWJlMWI2NDk4NDVjZjJhOTBlMjQgMg==&remote_epc_file_location=aHR0cDovL2xvY2FsaG9zdDoyMjIyL05PX0VYVC82NmVjMWJlMWI2NDk4NDVjZjJhOTBlMjMgMl9ub2NvbG9ybWFwX3ppcA==&h5filename=PBENOIT_JEANEZMAR_030_rqiDyn.h5


aHR0cDovL2xvY2FsaG9zdDoyMjIyL05PX0VYVC82NmVjMWJlMWI2NDk4NDVjZjJhOTBlMjMgMl9ub2NvbG9ybWFwX3ppcA==
