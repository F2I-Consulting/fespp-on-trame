"""vtkDescriptiveStatistics' two model tables, whatever the container.

VTK 9.5 (ParaView 6.0) returns a vtkMultiBlockDataSet, VTK 9.6 (ParaView 6.1)
a vtkPartitionedDataSetCollection, with the same two tables in the same order.
A reader that only knows `GetBlock` leaves the Statistics view empty on 6.1."""
from vtkmodules.vtkCommonDataModel import (
    vtkMultiBlockDataSet, vtkPartitionedDataSet, vtkPartitionedDataSetCollection,
    vtkTable)

from fespp_on_trame.engine.stats_dispatch import _statistics_tables


def _tables():
    primary, derived = vtkTable(), vtkTable()
    primary.SetObjectName("primary")
    derived.SetObjectName("derived")
    return primary, derived


def test_a_multiblock_output_gives_its_two_blocks():
    primary, derived = _tables()
    mb = vtkMultiBlockDataSet()
    mb.SetBlock(0, primary)
    mb.SetBlock(1, derived)
    got = _statistics_tables(mb)
    assert [t.GetObjectName() for t in got] == ["primary", "derived"]


def test_a_partitioned_collection_gives_its_two_tables():
    primary, derived = _tables()
    pdc = vtkPartitionedDataSetCollection()
    for i, table in enumerate((primary, derived)):
        pds = vtkPartitionedDataSet()
        pds.SetPartition(0, table)
        pdc.SetPartitionedDataSet(i, pds)
    got = _statistics_tables(pdc)
    assert [t.GetObjectName() for t in got] == ["primary", "derived"]


def test_no_output_and_a_single_table_say_so():
    assert _statistics_tables(None) == (None, None)
    primary, _ = _tables()
    mb = vtkMultiBlockDataSet()
    mb.SetBlock(0, primary)
    got = _statistics_tables(mb)
    assert got[0].GetObjectName() == "primary" and got[1] is None
