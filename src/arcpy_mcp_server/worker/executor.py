def execute(tool_id, parameters):
    import arcpy

    from tool_bindings import BINDINGS

    binding = BINDINGS.get(tool_id)
    if binding is None:
        return {
            "ok": False,
            "error_code": "TOOL_NOT_ALLOWED",
            "message": "tool ID is not bound by the ArcPy worker",
        }
    arcpy.env.overwriteOutput = False
    arcpy.env.processorType = "CPU"
    try:
        with arcpy.EnvManager(
            workspace=parameters["work_dir"],
            scratchWorkspace=parameters["work_dir"],
        ):
            result = binding(arcpy, parameters)
        return {
            "ok": True,
            "result": result,
            "messages": {
                "all": arcpy.GetMessages(0),
                "warnings": arcpy.GetMessages(1),
                "errors": arcpy.GetMessages(2),
            },
        }
    except arcpy.ExecuteError:
        return {
            "ok": False,
            "error_code": "ARCPY_EXECUTION_FAILED",
            "message": arcpy.GetMessages(2),
            "messages": {"all": arcpy.GetMessages(0)},
        }
    except Exception as error:
        return {
            "ok": False,
            "error_code": "WORKER_EXECUTION_FAILED",
            "message": f"{type(error).__name__}: {error}",
        }
