from ipaddress import ip_address

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509.oid import ExtendedKeyUsageOID

from arcpy_mcp_server.tls_bootstrap import generate_certificates


def test_generated_server_certificate_is_signed_for_fixed_ip(tmp_path):
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    output_dir = tmp_path / "local-app-data" / "certs"

    paths = generate_certificates(
        output_dir,
        ip_address("198.51.100.10"),
        repository_root=repository_root,
    )

    ca = x509.load_pem_x509_certificate(paths.ca_certificate.read_bytes())
    server = x509.load_pem_x509_certificate(
        paths.server_certificate.read_bytes()
    )
    assert ca.extensions.get_extension_for_class(
        x509.BasicConstraints
    ).value.ca
    assert ip_address("198.51.100.10") in server.extensions.get_extension_for_class(
        x509.SubjectAlternativeName
    ).value.get_values_for_type(x509.IPAddress)
    assert ExtendedKeyUsageOID.SERVER_AUTH in server.extensions.get_extension_for_class(
        x509.ExtendedKeyUsage
    ).value
    ca.public_key().verify(
        server.signature,
        server.tbs_certificate_bytes,
        padding.PKCS1v15(),
        server.signature_hash_algorithm,
    )
    assert not paths.ca_private_key.is_relative_to(repository_root)
    assert not paths.server_private_key.is_relative_to(repository_root)


def test_certificate_bootstrap_is_idempotent_without_rotation(tmp_path):
    output_dir = tmp_path / "certs"
    first = generate_certificates(output_dir, ip_address("198.51.100.10"))
    original = first.server_certificate.read_bytes()

    second = generate_certificates(output_dir, ip_address("198.51.100.10"))

    assert second == first
    assert second.server_certificate.read_bytes() == original


def test_private_keys_cannot_be_written_inside_repository(tmp_path):
    repository_root = tmp_path / "repository"
    output_dir = repository_root / "certs"

    with pytest.raises(ValueError, match="outside the repository"):
        generate_certificates(
            output_dir,
            ip_address("198.51.100.10"),
            repository_root=repository_root,
        )

