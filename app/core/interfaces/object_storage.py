from abc import ABC, abstractmethod


class IObjectStorage(ABC):
    """Port for persisting a binary object to external storage.

    Callers own their own key naming (namespacing, extension, uniqueness) --
    this port only knows how to write bytes to a key and does not generate one
    itself, so it stays reusable across every module that stores a file
    (receipt photos here, consent PDFs for valores_de_hierro later) against
    the same underlying bucket.
    """

    @abstractmethod
    async def save(self, *, key: str, content_type: str, data: bytes) -> None:
        """Persist ``data`` under ``key``.

        Raises:
            ObjectStorageError: the backend could not store the object.
        """
        ...
