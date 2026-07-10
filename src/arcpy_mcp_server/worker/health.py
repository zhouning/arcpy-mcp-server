def collect_health():
    import arcpy

    return {
        "install": arcpy.GetInstallInfo(),
        "product": arcpy.ProductInfo(),
        "extensions": {
            "Spatial": arcpy.CheckExtension("Spatial"),
            "ImageAnalyst": arcpy.CheckExtension("ImageAnalyst"),
        },
        "processor_type": "CPU",
        "tools": {
            "DetectObjectsUsingDeepLearning": hasattr(
                arcpy.ia, "DetectObjectsUsingDeepLearning"
            ),
            "ClassifyPixelsUsingDeepLearning": hasattr(
                arcpy.ia, "ClassifyPixelsUsingDeepLearning"
            ),
            "DetectChangeUsingDeepLearning": hasattr(
                arcpy.ia, "DetectChangeUsingDeepLearning"
            ),
        },
    }
