from paraview.simple import *
LoadPlugin("/work/ttl/build-fespp/lib/paraview-5.13/plugins/Fespp/Fespp.so", ns=globals())
reader = EnergisticsPackagingConventionsEPCReader(registrationName="test")

reader.addfile = ["/tmp/tmpup30g_v5/66ec1be1b649845cf2a90e23 2.epc"]
reader.Selectors = ["/data"]  # Load the full data
dai = reader.GetDataInformation().DataInformation
data_assembly = dai.GetDataAssembly()
print(data_assembly.GetNumberOfChildren(0))