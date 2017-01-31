#     enc - A free utility for encrypting Python code bases.
#     Copyright (C) 2017 M. Tyler Springer

#     This program is free software: you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation, either version 3 of the License, or
#     (at your option) any later version.

#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU General Public License for more details.

#     You should have received a copy of the GNU General Public License
#     along with this program.  If not, see <http://www.gnu.org/licenses/>.

from cement.core.foundation import CementApp
from cement.core.controller import CementBaseController, expose
import ast, types

# TODO: Refactor code to use consistent naming conventions across project.

class Alias_Replace(ast.NodeTransformer):
    """Mutate tree such that all aliased imports are replaced with hash values, BEFORE code is colletively merged."""
    def __init__(self):
        self.new_alias = {}

    def visit_Import(self, node):
        """Replace all aliased imports in ast with hash(alias + system time)."""
        from Crypto.Hash import SHA256
        import time
        imports = []
        for import_name in node.names:
            if import_name.asname != None:
                h = SHA256.new()
                h.update(import_name.asname + str(time.time()))
                self.new_alias[import_name.asname] = 'a'+h.hexdigest()
                imports.append(ast.alias(name=import_name.name, asname=self.new_alias[import_name.asname]))
            else:
                imports.append(import_name)
        return ast.Import(imports)

    def visit_ImportFrom(self, node):
        """Replace all aliased 'from module import x as y' style imports in ast with hash(alias + system time)."""
        from Crypto.Hash import SHA256
        import time
        imports = []
        for import_name in node.names:
            if import_name.asname != None:
                h = SHA256.new()
                h.update(import_name.asname + str(time.time()))
                self.new_alias[import_name.asname] = 'a'+h.hexdigest()
                imports.append(ast.alias(name=import_name.name, asname=self.new_alias[import_name.asname]))
            else:
                imports.append(import_name)
        return ast.ImportFrom(module=node.module,names=imports,level=node.level)

    def visit_Call(self, node):
        """Replace an references to aliased imports with a hash value."""
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                if node.func.value.id in self.new_alias:
                    return ast.Call(func=ast.Attribute(value=ast.Name(id=self.new_alias[node.func.value.id], ctx=ast.Load()), attr=node.func.attr, ctx=ast.Load()), args=node.args, keywords=node.keywords, starargs=node.starargs, kwargs=node.kwargs)
        elif isinstance(node.func, ast.Name):
            if node.func.id in self.new_alias:
                return ast.Call(func=ast.Name(id=self.new_alias[node.func.id], ctx=ast.Load()), args=node.args, keywords=node.keywords, starargs=node.starargs, kwargs=node.kwargs)
        return node

class ModifyTree(ast.NodeTransformer):
    """Mutate import conflicts associated with having code in seperate modules."""
    def __init__(self, importsToRemove, possibleModules, aliasMap, reverseAliasMap):
        self.importsToRemove = importsToRemove
        self.possibleModules = possibleModules
        self.aliasMap = aliasMap
        self.reverseAliasMap = reverseAliasMap

    def visit_Import(self, node):
        """Remove import statements for modules that will be concatenated."""
        for candidate in self.possibleModules:
            for name in node.names:
                if candidate == name.name:
                    node.names.remove(name)
        if len(node.names) == 0:
            return None
        return node

    def visit_ImportFrom(self, node):
        """Remove 'from module import x' style imports from modules that will be concatenated."""
        if node.module in self.possibleModules:
            return None
        return node

    def visit_Call(self, node):
        """Fix method calls that would have previously imported an external module such that scripts can be safely concatenated."""
        if isinstance(node.func, ast.Attribute):
        # If the method call is in the form A.B() replace this with B() if module A was imported
            if isinstance(node.func.value, ast.Name):
                if node.func.value.id in self.importsToRemove: # call.attribute.name.string
                    return ast.Call(func=ast.Name(id=node.func.attr, ctx=ast.Load()), args=node.args, keywords=node.keywords, starargs=node.starargs, kwargs=node.kwargs)
        elif isinstance(node.func, ast.Name):
        # If the method call is in the form D.B() replace this with B() if module A was imported as D (Aliased)
            if node.func.id in self.reverseAliasMap:
            # if the method call is in the from D() when 'from X import C as D' so that it becomes C()
                try:
                    return ast.Call(func=ast.Name(id=self.reverseAliasMap[node.func.id], ctx=ast.Load()), args=node.args, keywords=node.keywords, starargs=node.starargs, kwargs=node.kwargs)
                except KeyError:
                    pass
            if node.func.id in self.importsToRemove:
                try:
                    return ast.Call(func=ast.Name(id=self.reverseAliasMap[node.func.id], ctx=ast.Load()), args=node.args, keywords=node.keywords, starargs=node.starargs, kwargs=node.kwargs)
                except KeyError:
                    pass
        return node

class SpecialtyVisitor(ast.NodeVisitor):
    """Gather preliminary information of layout of modules that will be merged."""
    def __init__(self, possibleModules):
        self.stack = 0
        self.classDefinitions = []
        self.alias = {}
        self.reverse_alias = {}
        self.importsToRemove = []
        self.possibleModules = possibleModules # This would come from the commandline args in enc.py
        self.formattedModules = []

    def visit_ClassDef(self, node):
        """Record the name of each class defined in source and store it in an instance level list."""
        self.classDefinitions.append(node.name)
        self.generic_visit(node)

    def visit_Import(self, node):
        """Build instance level alias maps from regular import statements such that if 'import A as B' there would be A -> B, and also B -> A."""
        for importStatement in node.names:
            if importStatement.asname != None:
                self.alias[importStatement.name] = importStatement.asname
                self.reverse_alias[importStatement.asname] = importStatement.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        """Build instance level alias maps from 'from module import x' style imports such that if 'from D import A as B' there would be A -> B, and also B -> A."""
        for importStatement in node.names:
            if importStatement.asname != None:
                self.alias[importStatement.name] = importStatement.asname
                self.reverse_alias[importStatement.asname] = importStatement.name
        self.generic_visit(node)

    def resolve(self):
        """Determines which imports can be safely removed and stores them in an instance level list."""
        import os
        for mod in self.possibleModules:
            module_name = os.path.splitext(self.extract_filename(mod))[0] # 'A.py' -> 'A'
            self.formattedModules.append(module_name)
            if module_name in self.alias:
                self.importsToRemove.append(self.alias[module_name]) 
            else:
                self.importsToRemove.append(module_name)

    def extract_filename(self, path):
        import ntpath
        head, tail = ntpath.split(path)
        return tail or ntpath.basename(head)

class SourceEncryptor(object):
    """Merges source code, resolves dependency problems and then encrypts a Python AST object that can be run later."""
    def __init__(self):
        pass

    def merge_and_encrypt(self, sources, entry, secret, storage_type, compress, debug):
        """Driver methos that merges code, encodes it, encrypts it and writes it to a file"""
        merged_source_ast = self.merge_source_code(sources, entry)
        merged_source_ast = self.resolve_imports(merged_source_ast, sources)
        merged_source_ast = self.reorder_imports(merged_source_ast)
        if storage_type == 'a': #store file either as an AST or as raw source code
            import cPickle
            output_data = cPickle.dumps(merged_source_ast, protocol=cPickle.HIGHEST_PROTOCOL)
        else:
            import re, astunparse
            output_data = re.sub("[\n]+", "\n", astunparse.unparse(merged_source_ast))

        if compress:
            output_data = self.compress_data(output_data)

        if debug:
            import astunparse
            print astunparse.unparse(merged_source_ast) # This can be captured and run for debugging purposes, i.e. `python enc.py xxx > out.py`

        return self.encrypt(output_data, secret) # returns a tuple (computed_iv, encrypted source)

    def resolve_imports(self, tree, sources):
        """Call tree helper methods and classes in order to fix import issues associated with merging modules. Repair AST after modifications and return tree."""
        information_gatherer = SpecialtyVisitor(sources)
        information_gatherer.visit(tree)
        information_gatherer.resolve()
        transformed = ModifyTree(information_gatherer.importsToRemove, information_gatherer.formattedModules, information_gatherer.alias, information_gatherer.reverse_alias)
        transformed.visit(tree)
        ast.fix_missing_locations(tree)
        return tree

    def reorder_imports(self, tree):
        """Reorder module level imports so that they are all at the top of the source."""
        imports = []
        for node in tree.body:
            if isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
                imports.append(node)
        for import_stmt in imports:
            tree.body.remove(import_stmt)
        new_tree_root = ast.Module(imports)
        new_tree_root.body += tree.body
        return ast.fix_missing_locations(new_tree_root)

    def compress_data(self, data):
        """Compress AST object using zlib for more compact on-disk storage"""
        import zlib
        return zlib.compress(data)

    def encrypt(self, source, secret):
        """Encrypt merged source code using a hashed secret and AES encryption. Return as a tuple containing (string: iv, string: encyrpted_source)"""
        from Crypto.Cipher import AES
        from Crypto.Hash import SHA256
        from Crypto.Random import random

        h = SHA256.new()
        h_iv = SHA256.new()
        
        h.update(bytes(secret))
        h_iv.update(bytes(random.getrandbits(256)))
        computed_iv = h_iv.digest()[:16]

        encryptor = AES.new(h.digest(), AES.MODE_CBC, computed_iv) #Use only the first 16 bytes of the IV hash value
        if len(source) % 16 != 0:
            source += ' ' * (16 - len(source) % 16) # Should note that padding could harm PEP8 compliance...perhaps remove whitespace in Run application
        return (computed_iv, encryptor.encrypt(source))

    def merge_source_code(self, sources, entry):
        """Merge multiple python source files and returns them as an AST object."""
        tree = None
        for source in sources:
            if source != entry:
                if not tree:
                    tree = self.sanitize_source(source, False)
                else:
                    tree.body += self.sanitize_source(source, False).body
        if tree:
            tree.body += self.sanitize_source(entry, True).body
        else:
            tree = self.sanitize_source(entry, True)
        return tree #returns an ast

        # Note: There is no reason to bring it back to a human readable version unless its for debugging

    def sanitize_source(self, source, entry=False):
        """Fix aliasing conflicts and remove any module level code that is not a ClassDef, FunctionDef, Import or ImportFrom provided it is not from the source file containing the application entry point."""
        with open(source, 'r') as fin:
            root = ast.parse(fin.read())
        fixed_aliasing = Alias_Replace()
        fixed_aliasing.visit(root)
        ast.fix_missing_locations(root)
        if not entry:
            for node in root.body: 
                if not isinstance(node, ast.ClassDef) and not isinstance(node, ast.FunctionDef) and not isinstance(node, ast.Import) and not isinstance(node, ast.ImportFrom):
                    root.body.remove(node) # This could be a problem, may need to refactor
        return root

class CLIController(CementBaseController):
    """CLI Controller built using the Cement CLI Framework."""
    class Meta:
        label = 'base'
        description = "Tool for encrypting multiple python source files into a single unit that can be run from the RUN utility."
        arguments = [
            (['-e', '--entry'], dict(action='store', dest='entry', help='Specify file as application entry point')),
            (['-s', '--source'], dict(action='store', dest='source', nargs='*', help='Space seperated list of source files to be encrypted')),
            (['-p', '--password'], dict(action='store', dest='password', help='Password/Secret used to encrypt source files')),
            (['-o', '--output'], dict(action='store', dest='output', default='output.enc', help="Specify output path and filename")),
            (['-t', '--type'], dict(action='store', dest='storage_type', choices=['a','r'], default='a', help="Specify how code should be stored in the encrypted file. For AST (compatability) use 'a'. For raw code (file size) use 'r'")),
            (['-c', '--compress'], dict(action='store_true', dest='compress', help="Compress output format for reduced filesize (zlib)")),
            (['-d', '--debugOutput'], dict(action='store_true', dest='debug', help="Prints the approximate source code that will be placed into the runnable unit (before encryption)")),
            (['-l', '--load'], dict(action='store', dest='load', help="Load in a single file to be encrypted. Mainly used after correcting issues while debugging."))
        ]

    @expose(hide=True)
    def default(self):
        se = SourceEncryptor()
        if self.app.pargs.load and self.app.pargs.password:
            import cPickle
            tree = se.sanitize_source(self.app.pargs.load, True)
            tree = cPickle.dumps(tree)
            iv, enc_source = se.encrypt(tree, self.app.pargs.password)
            self.write_to_file(iv, enc_source)
        if self.app.pargs.entry and self.app.pargs.source and self.app.pargs.password:
            iv, enc_source = se.merge_and_encrypt(self.app.pargs.source, self.app.pargs.entry, self.app.pargs.password, self.app.pargs.storage_type, self.app.pargs.compress, self.app.pargs.debug)
            self.write_to_file(iv, enc_source)

    def write_to_file(self,iv, enc_source):
        with open(self.app.pargs.output,'wb') as fout:
                if self.app.pargs.compress:
                    fout.write('c')                          #compressed
                else:
                    fout.write('u')                          #uncompressed
                fout.write(self.app.pargs.storage_type)      #storage_type code
                fout.write(iv)                               #initialization vector
                fout.write(enc_source)                       #encrypted source
class CLIApplication(CementApp):
    class Meta:
        label = "enc"
        base_controller = "base"
        handlers = [CLIController]

if __name__ == "__main__":
    with CLIApplication() as app:
        app.run()
