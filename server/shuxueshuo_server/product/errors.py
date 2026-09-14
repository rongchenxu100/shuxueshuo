class ProductError(ValueError):
    code = 'product.invalid'


class Conflict(ProductError):
    code = 'product.conflict'


class Forbidden(ProductError):
    code = 'product.forbidden'


class IntegrityFailure(ProductError):
    code = 'product.integrity'


class NotFound(ProductError):
    code = 'product.not_found'
