"""Guy4ASE uses only stable ASE2SPRKKR runtime contracts."""


def test_file_version_compatibility_module_uses_public_backend_contract():
    from ase2sprkkr import FileState, FileVersion, FileVersionCaptureError
    from guy4ase.gui.application import file_version

    assert file_version.FileState is FileState
    assert file_version.FileVersion is FileVersion
    assert file_version.FileVersionCaptureError is FileVersionCaptureError


def test_result_loading_uses_public_potential_exception():
    from ase2sprkkr import PotentialFileChanged
    from guy4ase.gui.application import result_loading

    assert result_loading.PotentialFileChanged is PotentialFileChanged
