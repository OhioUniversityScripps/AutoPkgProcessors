#!/usr/bin/python

import json
import os
import plistlib
import re
import subprocess
import sys

from autopkglib import Processor, ProcessorError
from slackclient import SlackClient

__all__ = ["MunkiServerUploader"]


class MunkiServerUploader(Processor):
    """Uploads a package to munkiserver"""

    description = __doc__

    input_variables = {
        "api_url": {
            "required": False,
            "default": os.environ.get("MUNKISERVER_API_URL"),
            "description": "The address of the munkiserver package creation API endpoint.",
        },
        "api_key": {
            "required": False,
            "default": os.environ.get("MUNKISERVER_API_KEY"),
            "description": "A key which grants access to the munkiserver API.",
        },
        "unit": {
            "required": False,
            "default": os.getenv("MUNKISERVER_UNIT", "communication"),
            "description": "The munkiserver unit associated with this package.",
        },
        "package_file": {
            "required": False,
            "default": os.environ.get("pathname"),
            "description": "The package to be uploaded.",
        },
        "pkginfo_file": {
            "required": False,
            "description": "The pkginfo file to go with the package (optional).",
        },
        "pkginfo_name": {
            "required": False,
            # Custom makepkginfo option
            "default": os.environ.get("PKGINFO_NAME"),
            "description": "Passed to makepkginfo --name",
        },
        "pkginfo_displayname": {
            "required": False,
            # Custom makepkginfo option
            "default": os.environ.get("PKGINFO_DISPLAYNAME"),
            "description": "Passed to makepkginfo --displayname",
        },
        "pkginfo_destinationpath": {
            "required": False,
            "description": "Passed to makepkginfo --destinationpath",
        },
        "CURL_PATH": {
            "required": False,
            "default": "/usr/bin/curl",
            "description": "Path to curl binary. Defaults to /usr/bin/curl.",
        },
        "slack_api_token": {
            "required": False,
            "default": os.environ.get("SLACK_API_TOKEN"),
            "description": "The token used for Slack API access.",
        },
    }
    output_variables = {
        "munkiserver_uploader_summary_result": {
            "description": "Response from munkiserver.",
        },
    }

    def make_pkg_info(self, package_file):
        args = ["/usr/local/munki/makepkginfo", self.env["package_file"]]
        if self.env.get("pkginfo_name"):
            args.extend(["--name", self.env["pkginfo_name"]])
        if self.env.get("pkginfo_displayname"):
            args.extend(["--displayname", self.env["pkginfo_displayname"]])
        if self.env.get("pkginfo_destinationpath"):
            args.extend(
                ["--destinationpath", self.env["pkginfo_destinationpath"]])

        self.env["pkginfo_file"] = self.env["package_file"] + '.plist'
        with open(self.env["pkginfo_file"], "wb") as pkginfo_file_handle:
            self.output("No pkginfo file specified.  Creating " +
                        self.env["pkginfo_file"])
            p = subprocess.call(args, stdout=pkginfo_file_handle)

        # Preemptively fix the version number, replacing characters known to break munki with underscores
        plist = plistlib.readPlist(self.env["pkginfo_file"])
        plist["name"] = re.sub('[^a-zA-Z0-9.-]+', '_', plist["name"])
        plist["version"] = re.sub('[^a-zA-Z0-9.-]+', '_', plist["version"])
        plistlib.writePlist(plist, self.env["pkginfo_file"])

    def send_slack_notification(self, message):
        sc = SlackClient(self.env["slack_api_token"])
        chan = "munkiserver-packages"
        result = sc.api_call("chat.postMessage", as_user="false",
                             username="jenkins", channel=chan, text=message)
        if not result["ok"]:
            self.output("Failed to send Slack notification: " + result)

    def main(self):

        if not self.env["package_file"]:
            if self.env["pathname"]:
                self.env["package_file"] = self.env["pathname"]
            else:
                self.output("No package file pathname provided")
                return

        if not os.path.exists(self.env["package_file"]):
            self.output("package_file path:  " + self.env["package_file"])
            self.output("Package file not found")
            return

        if not "pkginfo_file" in self.env:
            # Generate arguments for makepkginfo.
            self.make_pkg_info(self.env["package_file"])
        else:
            if not os.path.exists(self.env["pkginfo_file"]):
                self.output("pkginfo file specified but not found")
                return
        pkginfo = plistlib.readPlist(self.env["pkginfo_file"])
        app_name = pkginfo["name"]
        app_version = pkginfo["version"]

        # If this version of the package already exists in munkiserver then exit.
        try:
            api_url = self.env["api_url"] + "/" + self.env["unit"] + \
                "/packages/" + app_name + "/" + app_version
            # Uncomment to debug:
            # self.output("Building the call to " + api_url)
            curl_cmd = [self.env["CURL_PATH"],
                        '--header', 'X-Api-Key: ' + self.env["api_key"],
                        '--url', api_url]
        except:
            self.output(
                "Unable to construct curl command.  Have you set the MUNKISERVER_API_URL, MUNKISERVER_API_KEY, and MUNKISERVER_UNIT environment variables?")
            return
        p = subprocess.Popen(
            curl_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        response = json.loads(p.stdout.read())
        # Uncomment to debug:
        # self.output(response)
        if response["exists"]:
            self.output(app_name + " version " + app_version +
                        " is already in munkiserver.  Quitting.")
            return

        # Attempt to upload the package
        try:
            api_url = self.env["api_url"] + "/" + \
                self.env["unit"] + "/packages"
            curl_cmd = [self.env["CURL_PATH"],
                        '--header', 'X-Api-Key: ' + self.env["api_key"],
                        '-F', 'pkginfo_file=@' + self.env["pkginfo_file"],
                        '-F', 'package_file=@' + self.env["package_file"],
                        '--url', api_url]
        except:
            self.output(
                "Unable to construct curl command.  Have you set the MUNKISERVER_API_URL, MUNKISERVER_API_KEY, and MUNKISERVER_UNIT environment variables?")
            return

        p = subprocess.Popen(
            curl_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        response = json.loads(p.stdout.read())
        if response["type"] == "success":
            self.output("Upload succeeded: " + response['message'])
            self.output("URL: " + response['edit_url'])
            self.send_slack_notification(
                "A new package has been uploaded to Staging.  Please check the settings, test it, and put it into production:  " + response["edit_url"])

        else:
            self.output('Upload failed: ' + response['message'])

        return


if __name__ == "__main__":
    PROCESSOR = MunkiServerUploader()
    PROCESSOR.execute_shell()
