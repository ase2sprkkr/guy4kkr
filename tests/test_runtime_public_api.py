"""Guy4ASE uses documented ASE2SPRKKR module-level contracts."""


def test_file_version_compatibility_module_uses_public_backend_contract():
    from ase2sprkkr.execution import (
        FileState,
        FileVersion,
        FileVersionCaptureError,
    )
    from guy4ase.gui.application import file_version, potential_version

    assert file_version.FileState is FileState
    assert file_version.FileVersion is FileVersion
    assert file_version.FileVersionCaptureError is FileVersionCaptureError
    assert potential_version.PotentialFileVersion is FileVersion


def test_result_loading_uses_potential_exception_from_its_defining_module():
    from ase2sprkkr.potentials.potentials import PotentialFileChanged
    from guy4ase.gui.application import result_loading

    assert result_loading.PotentialFileChanged is PotentialFileChanged
