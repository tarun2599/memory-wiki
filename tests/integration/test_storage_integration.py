"""Integration tests using moto for S3 and in-memory components."""

import boto3
import pytest
from moto import mock_aws

from app.services.memory_store import MemoryStore
from app.services.storage import ObjectStorage


@pytest.fixture
def s3_storage(monkeypatch: pytest.MonkeyPatch) -> ObjectStorage:
    with mock_aws():
        monkeypatch.setenv("S3_ENDPOINT", "http://localhost:5000")
        monkeypatch.setattr("app.config.settings.s3_endpoint", "http://localhost:5000")
        monkeypatch.setattr("app.config.settings.s3_bucket", "test-memories")
        monkeypatch.setattr("app.config.settings.memory_prefix", "wiki/")

        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-memories")

        storage = ObjectStorage()
        yield storage


class TestObjectStorageIntegration:
    def test_put_and_get_roundtrip(self, s3_storage: ObjectStorage) -> None:
        s3_storage.put_object("topics/python.md", "# Python\n\nGreat language.", {"title": "Python"})
        content, metadata, _ = s3_storage.get_object("topics/python.md")
        assert "Python" in content
        assert metadata["title"] == "Python"

    def test_list_objects_hierarchy(self, s3_storage: ObjectStorage) -> None:
        s3_storage.put_object("entities/people/alice.md", "# Alice")
        s3_storage.put_object("entities/people/bob.md", "# Bob")
        s3_storage.put_object("entities/organizations/acme.md", "# Acme")

        root = s3_storage.list_objects("")
        root_names = {e["name"] for e in root}
        assert "entities" in root_names

        people = s3_storage.list_objects("entities/people")
        people_names = {e["name"] for e in people}
        assert "alice.md" in people_names
        assert "bob.md" in people_names

    def test_list_all_files_recursive(self, s3_storage: ObjectStorage) -> None:
        s3_storage.put_object("a/x.md", "x")
        s3_storage.put_object("a/b/y.md", "y")
        files = s3_storage.list_all_files("")
        assert "a/x.md" in files
        assert "a/b/y.md" in files

    def test_object_not_found(self, s3_storage: ObjectStorage) -> None:
        with pytest.raises(FileNotFoundError):
            s3_storage.get_object("missing.md")


class TestMemoryStoreWithS3:
    def test_full_workflow(self, s3_storage: ObjectStorage) -> None:
        store = MemoryStore(storage=s3_storage)
        store.write_memory_file("entities/people", "diana", "# Diana\n\nProduct manager.")
        store.write_memory_file("topics", "roadmap", "# Roadmap\n\nQ3 priorities.")

        ls_result = store.ls("entities/people")
        assert any(e.name == "diana.md" for e in ls_result.entries)

        cat_result = store.cat("entities/people/diana.md")
        assert "Product manager" in cat_result.content

        grep_result = store.grep("roadmap", ignore_case=True)
        assert grep_result.total_matches >= 1
