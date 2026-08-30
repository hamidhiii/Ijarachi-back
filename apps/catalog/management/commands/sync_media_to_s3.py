from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        'Uploads files already lying in MEDIA_ROOT to the configured S3 bucket, '
        'keeping their relative paths so existing ImageField values keep resolving. '
        'Requires USE_S3=True. Run once when switching media storage to the bucket.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--prefix', default='',
            help='Upload only this subtree of MEDIA_ROOT, e.g. items/ or kyc/',
        )
        parser.add_argument('--dry-run', action='store_true', help='List what would be uploaded, upload nothing')
        parser.add_argument(
            '--force', action='store_true',
            help='Re-upload files that already exist in the bucket (otherwise they are skipped)',
        )

    def handle(self, *args, **options):
        if not settings.USE_S3:
            raise CommandError('USE_S3 is False — default_storage is the local disk, nothing to sync to')
        if not settings.AWS_STORAGE_BUCKET_NAME:
            raise CommandError('AWS_STORAGE_BUCKET_NAME is not set')

        media_root = Path(settings.MEDIA_ROOT)
        source = media_root / options['prefix'] if options['prefix'] else media_root
        if not source.is_dir():
            raise CommandError(f'{source} does not exist')

        dry_run, force = options['dry_run'], options['force']
        uploaded = skipped = failed = 0

        for path in sorted(p for p in source.rglob('*') if p.is_file()):
            # ключ в бакете = путь относительно MEDIA_ROOT, тот же, что хранится в БД
            name = path.relative_to(media_root).as_posix()

            already_there = default_storage.exists(name)
            if already_there and not force:
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(f'would upload {name}')
                uploaded += 1
                continue

            try:
                # AWS_S3_FILE_OVERWRITE=False, иначе save() на существующем ключе создаст
                # копию с суффиксом вместо перезаписи — чистим ключ руками
                if already_there:
                    default_storage.delete(name)
                with path.open('rb') as fh:
                    saved = default_storage.save(name, File(fh))
            except Exception as exc:
                failed += 1
                self.stderr.write(self.style.ERROR(f'{name}: {exc}'))
                continue

            uploaded += 1
            self.stdout.write(f'uploaded {saved}')

        summary = f'uploaded: {uploaded}, skipped (already in bucket): {skipped}, failed: {failed}'
        style = self.style.ERROR if failed else self.style.SUCCESS
        self.stdout.write(style(summary))
