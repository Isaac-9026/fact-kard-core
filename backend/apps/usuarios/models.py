from django.db import models


class Usuario(models.Model):
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(max_length=254, unique=True)
    password_hash = models.CharField(max_length=255)
    es_admin_global = models.BooleanField(default=False, db_default=False)
    activo = models.BooleanField(default=True, db_default=True)

    class Meta:
        db_table = 'usuario'
        verbose_name = 'Usuario'
        verbose_name_plural = 'Usuarios'

    def __str__(self):
        return self.username

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def set_password(self, raw_password):
        from django.contrib.auth.hashers import make_password
        self.password_hash = make_password(raw_password)

    def check_password(self, raw_password):
        from django.contrib.auth.hashers import check_password
        return check_password(raw_password, self.password_hash)


class UsuarioEmpresa(models.Model):
    usuario = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.CASCADE,
        db_column='usuario_id',
        related_name='empresas_asignadas'
    )
    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.CASCADE,
        db_column='empresa_id',
        related_name='usuarios_asignados'
    )
    rol = models.CharField(max_length=20)
    activo = models.BooleanField(default=True, db_default=True)

    class Meta:
        db_table = 'usuario_empresa'
        verbose_name = 'Usuario por Empresa'
        verbose_name_plural = 'Usuarios por Empresa'
        constraints = [
            models.UniqueConstraint(
                fields=['usuario', 'empresa'],
                name='uq_usuario_empresa'
            ),
            models.CheckConstraint(
                condition=models.Q(rol__in=['ADMIN', 'USUARIO']),
                name='chk_usuario_empresa_rol'
            )
        ]

    def __str__(self):
        return f"{self.usuario.username} - {self.empresa.razon_social} ({self.rol})"


class TokenRevocado(models.Model):
    """
    Bloque 6: tokens invalidados por logout (lista de revocación por `jti`). Basta con
    conservarlos hasta su expiración; luego el token ya no es válido por sí mismo.
    """
    jti = models.CharField(max_length=64, unique=True)
    usuario = models.ForeignKey(
        'usuarios.Usuario', on_delete=models.CASCADE, db_column='usuario_id', related_name='tokens_revocados',
    )
    revocado_en = models.DateTimeField(auto_now_add=True)
    expira_en = models.DateTimeField()

    class Meta:
        db_table = 'token_revocado'
        # Bloque 7: la limpieza de revocaciones expiradas (en cada logout) filtra por expira_en.
        # La búsqueda por jti ya usa el índice único.
        indexes = [models.Index(fields=['expira_en'], name='ix_token_revocado_expira')]
