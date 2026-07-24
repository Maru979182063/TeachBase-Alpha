# Pipeline Control Plane Validation 20260714

- `python tools/validate_pipeline_registry.py --json`: exit `0`
- `python tests/test_pipeline_registry.py`: exit `0`
- Overall passed: `True`

## Unit Test Output

``text
python.exe : ...
At line:8 char:15
+ $unitOutput = & python tests/test_pipeline_registry.py 2>&1
+               ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : NotSpecified: (...:String) [], RemoteException
    + FullyQualifiedErrorId : NativeCommandError
 
----------------------------------------------------------------------
Ran 3 tests in 0.006s

OK
``
