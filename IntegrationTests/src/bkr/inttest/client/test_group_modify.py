import unittest
import email
from bkr.inttest import data_setup, with_transaction, mail_capture
from bkr.inttest.client import run_client, ClientError, create_client_config
from bkr.server.model import Group, Activity
from turbogears.database import session

class GroupModifyTest(unittest.TestCase):

    def setUp(self):
        with session.begin():
            self.user = data_setup.create_user(password = 'asdf')
            self.group = data_setup.create_group(owner=self.user)
            self.client_config = create_client_config(username=self.user.user_name,
                                                      password='asdf')

            rand_user = data_setup.create_user(password = 'asdf')
            rand_user.groups.append(self.group)
            self.rand_client_config = create_client_config(username=rand_user.user_name,
                                                           password='asdf')

            admin = data_setup.create_admin(password='password')
            self.admin_client_config = create_client_config(username=admin.user_name,
                                                            password='password')

        self.mail_capture = mail_capture.MailCaptureThread()
        self.mail_capture.start()

    def tearDown(self):
        self.mail_capture.stop()

    def check_notification(self, user, group, action):
        self.assertEqual(len(self.mail_capture.captured_mails), 1)
        sender, rcpts, raw_msg = self.mail_capture.captured_mails[0]
        self.assertEqual(rcpts, [user.email_address])
        msg = email.message_from_string(raw_msg)
        self.assertEqual(msg['To'], user.email_address)

        # headers and subject
        self.assertEqual(msg['X-Beaker-Notification'], 'group-membership')
        self.assertEqual(msg['X-Beaker-Group'], group.group_name)
        self.assertEqual(msg['X-Beaker-Group-Action'], action)
        for keyword in ['Group Membership', action, group.group_name]:
            self.assert_(keyword in msg['Subject'], msg['Subject'])

        # body
        msg_payload = msg.get_payload(decode=True)
        action = action.lower()
        for keyword in [action, group.group_name]:
            self.assert_(keyword in msg_payload, (keyword, msg_payload))

    def test_group_modify_no_criteria(self):
        try:
            out = run_client(['bkr', 'group-modify',
                              self.group.group_name],
                             config = self.client_config)
            self.fail('Must fail or die')
        except ClientError, e:
            self.assert_('Please specify an attribute to modify'
                         in e.stderr_output, e.stderr_output)


    def test_group_nonexistent(self):
        display_name = 'A New Group Display Name'
        try:
            out = run_client(['bkr', 'group-modify',
                              '--display-name', display_name,
                              'group-like-non-other'],
                             config = self.client_config)
            self.fail('Must fail or die')
        except ClientError, e:
            self.assert_('Group does not exist' in e.stderr_output,
                         e.stderr_output)

    def test_group_modify_invalid(self):
        display_name = 'A New Group Display Name'
        try:
            out = run_client(['bkr', 'group-modify',
                              '--display-name', display_name,
                              'random', self.group.group_name],
                             config = self.client_config)
            self.fail('Must fail or die')
        except ClientError, e:
            self.assert_('Exactly one group name must be specified' in
                         e.stderr_output, e.stderr_output)

    def test_group_modify_not_owner(self):
        display_name = 'A New Group Display Name'

        try:
            out = run_client(['bkr', 'group-modify',
                              '--display-name', display_name,
                              self.group.group_name],
                             config = self.rand_client_config)
            self.fail('Must fail or die')
        except ClientError, e:
            self.assert_('You are not an owner of group' in
                         e.stderr_output, e.stderr_output)

    def test_group_modify_display_name(self):
        display_name = 'A New Group Display Name'
        out = run_client(['bkr', 'group-modify',
                          '--display-name', display_name,
                          self.group.group_name],
                         config = self.client_config)

        with session.begin():
            session.refresh(self.group)
            group = Group.by_name(self.group.group_name)
            self.assertEquals(group.display_name, display_name)
            self.assertEquals(group.activity[-1].action, u'Changed')
            self.assertEquals(group.activity[-1].field_name, u'Display Name')
            self.assertEquals(group.activity[-1].user.user_id,
                              self.user.user_id)
            self.assertEquals(group.activity[-1].new_value, display_name)
            self.assertEquals(group.activity[-1].service, u'XMLRPC')

    def test_group_modify_group_name(self):
        group_name = 'mynewgroup'
        out = run_client(['bkr', 'group-modify',
                          '--group-name', group_name,
                          self.group.group_name],
                         config = self.client_config)

        with session.begin():
            session.refresh(self.group)
            group = Group.by_name(group_name)
            self.assertEquals(group.group_name, group_name)
            self.assertEquals(group.activity[-1].action, u'Changed')
            self.assertEquals(group.activity[-1].field_name, u'Name')
            self.assertEquals(group.activity[-1].user.user_id,
                              self.user.user_id)
            self.assertEquals(group.activity[-1].new_value, group_name)
            self.assertEquals(group.activity[-1].service, u'XMLRPC')

    def test_group_modify_group_and_display_names(self):
        display_name = 'Shiny New Display Name'
        group_name = 'shinynewgroup'
        out = run_client(['bkr', 'group-modify',
                          '--display-name', display_name,
                          '--group-name', group_name,
                          self.group.group_name],
                         config = self.client_config)

        with session.begin():
            session.refresh(self.group)
            group = Group.by_name(group_name)
            self.assertEquals(group.display_name, display_name)
            self.assertEquals(group.group_name, group_name)

    #https://bugzilla.redhat.com/show_bug.cgi?id=967799
    def test_group_modify_group_name_duplicate(self):
        with session.begin():
            group1 = data_setup.create_group(owner=self.user)
            group2 = data_setup.create_group(owner=self.user)

        try:
            out = run_client(['bkr', 'group-modify',
                              '--group-name', group1.group_name,
                              group2.group_name],
                             config = self.client_config)
            self.fail('Must fail or die')
        except ClientError, e:
            self.assert_('Group name already exists' in e.stderr_output)

    def test_admin_cannot_rename_protected_group(self):
        # See https://bugzilla.redhat.com/show_bug.cgi?id=961206
        protected_group_name = 'admin'
        with session.begin():
            group = Group.by_name(protected_group_name)
            expected_display_name = group.display_name

        # Run command as the default admin user
        try:
            out = run_client(['bkr', 'group-modify',
                              '--group-name', 'cannot_rename_admin',
                              '--display-name', 'this is also unchanged',
                              protected_group_name])
            self.fail('Must fail or die')
        except ClientError, e:
            self.assert_('Cannot rename protected group' in
                         e.stderr_output, e.stderr_output)

        # Check the whole request is ignored if the name change is rejected
        with session.begin():
            session.refresh(group)
            self.assertEquals(group.group_name, protected_group_name)
            self.assertEquals(group.display_name, expected_display_name)

        # However, changing just the display name is fine
        new_display_name = 'Tested admin group'
        out = run_client(['bkr', 'group-modify',
                          '--display-name', new_display_name,
                          protected_group_name])

        with session.begin():
            session.refresh(group)
            self.assertEquals(group.group_name, protected_group_name)
            self.assertEquals(group.display_name, new_display_name)

    def test_group_modify_add_member(self):
        with session.begin():
            user = data_setup.create_user()

        out = run_client(['bkr', 'group-modify',
                          '--add-member', user.user_name,
                          self.group.group_name],
                         config = self.client_config)

        with session.begin():
            session.refresh(self.group)
            group = Group.by_name(self.group.group_name)
            self.assert_(user.user_name in
                         [u.user_name for u in group.users])


        self.check_notification(user, group, action='Added')

        try:
            out = run_client(['bkr', 'group-modify',
                              '--add-member', 'idontexist',
                              self.group.group_name],
                             config = self.client_config)
            self.fail('Must fail or die')
        except ClientError, e:
            self.assert_('User does not exist' in
                         e.stderr_output, e.stderr_output)

        try:
            out = run_client(['bkr', 'group-modify',
                              '--add-member', user.user_name,
                              self.group.group_name],
                             config = self.client_config)
            self.fail('Must fail or die')
        except ClientError, e:
            self.assert_('User %s is already in group' % user.user_name in
                         e.stderr_output, e.stderr_output)

        with session.begin():
            session.refresh(self.group)
            group = Group.by_name(self.group.group_name)
            self.assertEquals(group.activity[-1].action, u'Added')
            self.assertEquals(group.activity[-1].field_name, u'User')
            self.assertEquals(group.activity[-1].user.user_id,
                              self.user.user_id)
            self.assertEquals(group.activity[-1].new_value, user.user_name)
            self.assertEquals(group.activity[-1].service, u'XMLRPC')

    def test_group_modify_remove_member(self):
        with session.begin():
            user = data_setup.create_user()
            self.group.users.append(user)
            session.flush()
            self.assert_(user in self.group.users)

        out = run_client(['bkr', 'group-modify',
                          '--remove-member', user.user_name,
                          self.group.group_name],
                         config = self.client_config)

        with session.begin():
            session.refresh(self.group)
            group = Group.by_name(self.group.group_name)
            self.assert_(user.user_name not in
                         [u.user_name for u in group.users])

        self.check_notification(user, group, action='Removed')
        with session.begin():
            session.refresh(self.group)
            group = Group.by_name(self.group.group_name)
            self.assertEquals(group.activity[-1].action, u'Removed')
            self.assertEquals(group.activity[-1].field_name, u'User')
            self.assertEquals(group.activity[-1].user.user_id,
                              self.user.user_id)
            self.assertEquals(group.activity[-1].old_value, user.user_name)
            self.assertEquals(group.activity[-1].new_value, '')
            self.assertEquals(group.activity[-1].service, u'XMLRPC')

        try:
            out = run_client(['bkr', 'group-modify',
                              '--remove-member', 'idontexist',
                              self.group.group_name],
                             config = self.client_config)
            self.fail('Must fail or die')
        except ClientError, e:
            self.assert_('User does not exist' in
                         e.stderr_output, e.stderr_output)
        try:
            out = run_client(['bkr', 'group-modify',
                              '--remove-member', user.user_name,
                              self.group.group_name],
                             config = self.client_config)
            self.fail('Must fail or die')
        except ClientError, e:
            self.assert_('No user %s in group' % user.user_name in
                         e.stderr_output, e.stderr_output)

        try:
            out = run_client(['bkr', 'group-modify',
                              '--remove-member', self.user.user_name,
                              self.group.group_name],
                             config = self.client_config)
            self.fail('Must fail or die')
        except ClientError, e:
            self.assert_('Cannot remove member' in
                         e.stderr_output, e.stderr_output)

        # remove the last group member/owner as 'admin'
        self.mail_capture.captured_mails[:]=[]
        out = run_client(['bkr', 'group-modify',
                          '--remove-member', self.user.user_name,
                          self.group.group_name], config=self.admin_client_config)
        self.check_notification(self.user, self.group, action='Removed')

        # try to remove self from admin group
        # first remove all other users except 'admin'
        group = Group.by_name('admin')
        group_users = group.users
        # remove  all other users from 'admin'
        for usr in group_users:
            if usr.user_id != 1:
                out = run_client(['bkr', 'group-modify',
                                  '--remove-member', usr.user_name,
                                  'admin'], config=self.admin_client_config)

        try:
            out = run_client(['bkr', 'group-modify',
                              '--remove-member', 'admin', 'admin'])
            self.fail('Must fail or die')
        except ClientError, e:
            self.assert_('Cannot remove member' in
                         e.stderr_output, e.stderr_output)
