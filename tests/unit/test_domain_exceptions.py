from app.exceptions.domain_exceptions import (
    BaseError,
    EstablishmentNotFoundError,
    ForbiddenError,
    PasswordNotFoundError,
    SubjectAlreadyExistsError,
    UnauthorizedError,
    UserAlreadyExistsError,
    UserEstablishmentNotFoundError,
    UserNotFoundError,
)


def test_user_not_found_error():
    e = UserNotFoundError("id123")
    assert isinstance(e, BaseError)
    assert "id123" in e.details
    assert "User not found" in e.title


def test_user_already_exists_error():
    e = UserAlreadyExistsError("foo@bar.com")
    assert isinstance(e, BaseError)
    assert "foo@bar.com" in e.details
    assert "User already exists" in e.title


def test_password_not_found_error():
    e = PasswordNotFoundError("id456")
    assert isinstance(e, BaseError)
    assert "id456" in e.details
    assert "password" in e.title or "password" in e.details


def test_unauthorized_error():
    e = UnauthorizedError()
    assert isinstance(e, BaseError)
    assert "Authentication credentials are missing or invalid." in e.details
    assert "Unauthorized" in e.title


def test_forbidden_error():
    e = ForbiddenError()
    assert isinstance(e, BaseError)
    assert "Forbidden" in e.title


def test_establishment_not_found_error():
    e = EstablishmentNotFoundError("id456")
    assert isinstance(e, BaseError)
    assert "id456" in e.details
    assert "Establishment not found" in e.title


def test_user_establishment_not_found_error():
    e = UserEstablishmentNotFoundError("estab-id", "user-id")
    assert isinstance(e, BaseError)
    assert "estab-id" in e.details
    assert "user-id" in e.details
    assert "User establishment not found" in e.title


def test_subject_already_exists_error():
    e = SubjectAlreadyExistsError(20000000)
    assert isinstance(e, BaseError)
    assert "20000000" in e.details
    assert "Subject already exists" in e.title
