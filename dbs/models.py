from __future__ import absolute_import, division, generators, nested_scopes, print_function, unicode_literals, with_statement

import json
import re
import logging

from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist
from django.db import models


logger = logging.getLogger(__name__)


class TaskDataQuerySet(models.QuerySet):
    pass


class TaskData(models.Model):
    json = models.TextField()

    objects = TaskDataQuerySet.as_manager()

    def __unicode__(self):
        return json.dumps(json.loads(self.json), indent=4)


class TaskQuerySet(models.QuerySet):
    def get_by_celery_id(self, celery_id):
        return self.get(celery_id=celery_id)

    def change_status_to_running(self, task_id):
        try:
            task = self.get_by_celery_id(task_id)
        except ObjectDoesNotExist:
            logger.error("There is no task with celery id '%s'", task_id)
        else:
            task.set_status_running(save=True)
            return task


class Task(models.Model):
    STATUS_PENDING  = 1
    STATUS_RUNNING  = 2
    STATUS_FAILED   = 3
    STATUS_SUCCESS  = 4
    _STATUS_NAMES   = {
        STATUS_PENDING: 'Pending',
        STATUS_RUNNING: 'Running',
        STATUS_FAILED:  'Failed',
        STATUS_SUCCESS: 'Successful',
    }

    TYPE_BUILD  = 1
    TYPE_MOVE   = 2
    _TYPE_NAMES = {
        TYPE_BUILD: 'Build',
        TYPE_MOVE:  'Move',
    }

    celery_id       = models.CharField(max_length=42, blank=True, null=True)
    date_started    = models.DateTimeField(auto_now_add=True)
    date_finished   = models.DateTimeField(null=True, blank=True)
    builddev_id     = models.CharField(max_length=38)
    status          = models.IntegerField(choices=_STATUS_NAMES.items(), default=STATUS_PENDING)
    type            = models.IntegerField(choices=_TYPE_NAMES.items())
    owner           = models.CharField(max_length=38)
    task_data       = models.ForeignKey(TaskData)

    objects = TaskQuerySet.as_manager()

    class Meta:
        ordering = ["-date_finished"]

    def __unicode__(self):
        return "%d [%s]" % (self.id, self.get_status())

    def get_type(self):
        return self._TYPE_NAMES[self.type]

    def get_status(self):
        return self._STATUS_NAMES[self.status]

    def set_status(self, status, save=True):
        self.status = status
        if save:
            self.save()

    def set_status_running(self, save=True):
        self.set_status(Task.STATUS_RUNNING, save)


class Package(models.Model):
    """ TODO: software collections """
    name = models.CharField(max_length=64)



class RpmQuerySet(models.QuerySet):
    def get_or_create_from_nvr(self, nvr):
        re_nvr = re.match("(.*)-(.*)-(.*)", nvr)
        if re_nvr:
            name, version, release = re_nvr.groups()
            p, _ = Package.objects.get_or_create(name=name)
            rpm, _ = Rpm.objects.get_or_create(package=p, nvr=nvr)
            return rpm
        else:
            logger.error("'%s' is not an N-V-R", nvr)



class Rpm(models.Model):
    package = models.ForeignKey(Package)
    nvr = models.CharField(max_length=128)
    part_of = GenericRelation('Content')

    objects = RpmQuerySet.as_manager()

    def __unicode__(self):
        return "%s: %s" % (self.package, self.nvr)



class Content(models.Model):
    """
    generic many to many
    """
    content_type = models.ForeignKey(ContentType)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')



class Registry(models.Model):
    url = models.URLField()



class YumRepo(models.Model):
    url = models.URLField()


class ImageQuerySet(models.QuerySet):
    def taskdata_for_imageid(self, image_id):
        return json.loads(self.get(hash=image_id).task.task_data.json)

    def children(self, image_id):
        return self.filter(parent=image_id)

    def children_as_list(self, image_id):
        return self.children(image_id).values_list('hash', flat=True)

    def invalidate(self, image_id):
        """
        TODO:
        make this more efficient

        :param image_id:
        :return:
        """
        count = 0
        to_invalidate = [image_id]
        while True:
            try:
                parent_image = to_invalidate.pop()
            except IndexError:
                break
            count += self.filter(hash=parent_image, image__is_invalidated=False).update(is_invalidated=True)
            to_invalidate.extend(self.children_as_list(parent_image))
        return count



class Image(models.Model):
    STATUS_BUILD    = 1
    STATUS_TESTING  = 2
    STATUS_STABLE   = 3
    STATUS_BASE     = 4
    _STATUS_NAMES   = {
        STATUS_BUILD:   'Built',
        STATUS_TESTING: 'Pushed-Testing',
        STATUS_STABLE:  'Pushed-Stable',
        STATUS_BASE:    'Base-Image',
    }

    hash        = models.CharField(max_length=64, primary_key=True)
    parent      = models.ForeignKey('self', null=True, blank=True)  # base images doesnt have parents
    task        = models.OneToOneField(Task, null=True, blank=True)
    status      = models.IntegerField(choices=_STATUS_NAMES.items(), default=STATUS_BUILD)
    content     = models.ManyToManyField(Content)
    dockerfile  = models.ForeignKey('Dockerfile', null=True, blank=True)
    is_invalidated = models.BooleanField(default=False)

    objects = ImageQuerySet.as_manager()

    def __unicode__(self):
        return u"%s: %s" % (self.hash[:12], self.get_status())

    def get_status(self):
        return self._STATUS_NAMES[self.status]

    @classmethod
    def create(cls, image_id, status, tags=None, task=None, parent=None, dockerfile=None):
        image, _ = cls.objects.get_or_create(hash=image_id, status=status)
        image.task = task
        image.parent = parent
        if dockerfile:
            image.dockerfile = dockerfile
        image.save()
        for tag in tags:
            t, _ = Tag.objects.get_or_create(name=tag)
            t.save()
            rel = ImageRegistryRelation(tag=t, image=image)
            rel.save()
        return image

    @property
    def tags(self):
        return Tag.objects.for_image_as_list(self)

    @property
    def children(self):
        return Image.objects.children(self)

    def ordered_rpms_list(self):
        return list(Rpm.objects.filter(part_of__image=self).values_list('nvr', flat=True).order_by("nvr"))

    @property
    def rpms_count(self):
        return Rpm.objects.filter(part_of__image=self).count()

    def add_rpms_list(self, nvr_list):
        """
        provide a list of RPM nvrs and link them to image
        """
        for nvr in nvr_list:
            rpm = Rpm.objects.get_or_create_from_nvr(nvr)
            if rpm:
                rpm_ct = ContentType.objects.get(model='rpm')
                content, _ = Content.objects.get_or_create(object_id=rpm.id, content_type=rpm_ct)
                self.content.add(content)



class TagQuerySet(models.QuerySet):
    def for_image(self, image):
        return self.filter(registry_bindings__image=image)

    def for_image_as_list(self, image):
        return list(self.for_image(image).values_list('name', flat=True))


# TODO: do relations with this
class Tag(models.Model):
    name = models.CharField(max_length=64)

    objects = TagQuerySet.as_manager()



class ImageRegistryRelation(models.Model):
    tag = models.ForeignKey(Tag, related_name="registry_bindings")
    image = models.ForeignKey(Image)
    registry = models.ForeignKey(Registry, blank=True, null=True)



class Dockerfile(models.Model):
    content = models.TextField()



